"""Per-preview raw-port rules owned by the existing privileged resource host."""

import re
import shlex
from ipaddress import IPv4Network, ip_address
from pathlib import Path

from .artifact_environment_docker import command, engine


PROXY_CGROUP_PATTERN = r"^system[.]slice/[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}[.]service$"
IPV6_DISABLED = {"net.ipv6.conf.all.disable_ipv6": "1", "net.ipv6.conf.default.disable_ipv6": "1"}
ROLES = ("postgres", "migration", "backend", "frontend")


def enabled(group):
    return group is not None and group.request.resources.hard_limits.preview_slots == 1


def addresses(network):
    configurations = network.get("IPAM", {}).get("Config", [])
    if (network.get("Driver") != "bridge" or network.get("Internal") is not True
            or network.get("EnableIPv6") is not False or len(configurations) != 1):
        raise ValueError("preview_network_ipv4_only_required")
    subnet = IPv4Network(configurations[0]["Subnet"])
    if (not subnet.is_private or subnet.prefixlen > 29
            or ip_address(configurations[0]["Gateway"]) != subnet[1]):
        raise ValueError("preview_network_address_pool_unsupported")
    return {role: str(subnet[index + 2]) for index, role in enumerate(ROLES)}


def endpoint(network_id, role):
    return {"Aliases": [role], "IPAMConfig": {"IPv4Address": addresses(
        engine("GET", "/networks/" + network_id))[role]}}


def _proxy_cgroup(value):
    if value is None or not re.fullmatch(PROXY_CGROUP_PATTERN, value):
        raise ValueError("preview_network_proxy_cgroup_unconfigured")
    path = Path("/sys/fs/cgroup")
    for part in value.split("/"):
        path /= part
        state = path.lstat()
        processes = (path / "cgroup.procs").stat(follow_symlinks=False)
        if (not path.is_dir() or path.is_symlink() or state.st_uid != 0 or state.st_mode & 0o022
                or processes.st_uid != 0 or processes.st_mode & 0o022):
            raise ValueError("preview_network_proxy_cgroup_not_controlled")
    return path.stat().st_ino


def _iptables(*arguments, required=True):
    return command(["/usr/sbin/iptables", "-w", "2", *arguments], required=required)


def _chain(name, rules, comment):
    existing = _iptables("-S", name, required=False)
    if existing.returncode == 1:
        _iptables("-N", name)
        for rule in rules:
            _iptables("-A", name, *rule[:-2], "-m", "comment", "--comment", comment, *rule[-2:])
    elif existing.returncode:
        raise ValueError("preview_network_firewall_unavailable")
    values = [shlex.split(line) for line in _iptables("-S", name).stdout.decode("utf-8").splitlines()
              if line.startswith("-A ")]
    if len(values) != len(rules):
        raise ValueError("preview_network_owned_chain_changed")
    for rule in rules:
        result = _iptables("-C", name, *rule[:-2], "-m", "comment", "--comment", comment,
                           *rule[-2:], required=False)
        if result.returncode:
            raise ValueError("preview_network_owned_chain_changed")


def authorize(network, binding, proxy_cgroup):
    """Install before any container starts; no UID or caller-supplied source identity."""
    identity = network["Id"]
    interface = "br-" + identity[:12]
    if ((network.get("Options") or {}).get("com.docker.network.bridge.name", interface) != interface
            or (network.get("Labels") or {}).get("cloudhelm.resource-binding") != binding):
        raise ValueError("preview_network_binding_mismatch")
    targets = addresses(network)
    inode = _proxy_cgroup(proxy_cgroup)
    index = (Path("/sys/class/net") / interface / "ifindex").read_text(encoding="utf-8").strip()
    if Path("/proc/sys/net/bridge/bridge-nf-call-iptables").read_text(encoding="utf-8").strip() != "1":
        raise ValueError("preview_network_bridge_filtering_required")
    command(["/usr/sbin/sysctl", "-w", f"net.ipv6.conf.{interface}.disable_ipv6=1"])
    comment = f"cloudhelm-preview:{binding}:{identity}:{index}:{inode}"
    names = {chain: "CHP" + chain[0] + identity[:20] for chain in ("OUTPUT", "INPUT", "FORWARD")}
    output, inbound, forward = [], [], []
    for role, port in (("frontend", "80"), ("backend", "8000")):
        output.append(["-p", "tcp", "-d", targets[role], "--dport", port,
                       "-m", "cgroup", "--path", proxy_cgroup, "-j", "ACCEPT"])
        inbound.append(["-p", "tcp", "-s", targets[role], "--sport", port,
                        "-m", "conntrack", "--ctstate", "ESTABLISHED", "-j", "ACCEPT"])
    # Migration is the existing gated, fixed recipe operation, never a preview route.
    for source, target, port in (("frontend", "backend", "8000"), ("backend", "postgres", "5432"),
                                 ("migration", "postgres", "5432")):
        pair = ["-i", interface, "-o", interface, "-p", "tcp"]
        forward.append(pair + ["-s", targets[source], "-d", targets[target], "--dport", port, "-j", "ACCEPT"])
        forward.append(pair + ["-s", targets[target], "-d", targets[source], "--sport", port,
                               "-m", "conntrack", "--ctstate", "ESTABLISHED", "-j", "ACCEPT"])
    for chain, rules in (("OUTPUT", output), ("INPUT", inbound), ("FORWARD", forward)):
        _chain(names[chain], rules + [["-j", "DROP"]], comment)
        for direction in (("-i", "-o") if chain == "FORWARD" else ("-o",) if chain == "OUTPUT" else ("-i",)):
            rule = [direction, interface, "-m", "comment", "--comment", comment, "-j", names[chain]]
            present = _iptables("-C", chain, *rule, required=False)
            if present.returncode == 1:
                _iptables("-I", chain, "1", *rule)
            elif present.returncode:
                raise ValueError("preview_network_firewall_unavailable")


def release(binding):
    """Called after the bound execution group stops, including crashed daemon cleanup."""
    owned = {}
    for chain in ("OUTPUT", "INPUT", "FORWARD"):
        for line in _iptables("-S", chain).stdout.decode("utf-8").splitlines():
            values = shlex.split(line)
            if "--comment" not in values:
                continue
            comment = values[values.index("--comment") + 1]
            match = re.fullmatch(r"cloudhelm-preview:(resource-[0-9a-f]{40}):([0-9a-f]{64}):([0-9]+):([0-9]+)", comment)
            if match is None or match[1] != binding:
                continue
            interface, target = "br-" + match[2][:12], "CHP" + chain[0] + match[2][:20]
            direction = values[2]
            if direction not in ({"-i", "-o"} if chain == "FORWARD" else {"-o"} if chain == "OUTPUT" else {"-i"}) or values != [
                    "-A", chain, direction, interface, "-m", "comment", "--comment", comment, "-j", target]:
                raise ValueError("preview_network_owned_jump_changed")
            owned.setdefault((interface, match[3]), []).append((chain, values[2:], target, comment))
    for (interface, index), rules in owned.items():
        path = Path("/sys/class/net") / interface
        if path.exists():
            if (path / "ifindex").read_text(encoding="utf-8").strip() != index or not (path / "bridge").is_dir():
                raise ValueError("preview_network_interface_identity_changed")
            command(["/usr/sbin/ip", "link", "delete", "dev", interface])
        targets = {}
        for chain, rule, target, comment in rules:
            targets[target] = comment
            _iptables("-D", chain, *rule)
        for target, comment in targets.items():
            lines = [shlex.split(line) for line in _iptables("-S", target).stdout.decode("utf-8").splitlines()
                     if line.startswith("-A ")]
            if any("--comment" not in values or values[values.index("--comment") + 1] != comment for values in lines):
                raise ValueError("preview_network_owned_chain_changed")
            _iptables("-F", target)
            _iptables("-X", target)
