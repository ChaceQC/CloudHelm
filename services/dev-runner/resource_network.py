"""Scoped intra-bridge forwarding without changing another daemon's firewall policy."""

import re
import shlex
from pathlib import Path

from modules.execution.docker_endpoint import use_socket
from .artifact_environment_docker import command, engine


def _rule(interface, comment):
    return ["-i", interface, "-o", interface, "-m", "comment", "--comment", comment, "-j", "ACCEPT"]


def authorize(boundary, request, network_id):
    if not re.fullmatch(r"[0-9a-f]{64}", network_id):
        raise ValueError("resource_network_identity_invalid")
    with use_socket(boundary.socket(request)):
        network = engine("GET", "/networks/" + network_id)
    binding = boundary.binding(request)
    interface = "br-" + network_id[:12]
    if (network.get("Id") != network_id or network.get("Driver") != "bridge" or not network.get("Internal")
            or (network.get("Labels") or {}).get("cloudhelm.resource-binding") != binding
            or (network.get("Options") or {}).get("com.docker.network.bridge.name", interface) != interface):
        raise ValueError("resource_network_binding_mismatch")
    index = int((Path("/sys/class/net") / interface / "ifindex").read_text(encoding="utf-8"))
    comment = f"cloudhelm:{binding}:{network_id}:{index}"
    rule = _rule(interface, comment)
    present = command(["/usr/sbin/iptables", "-w", "2", "-C", "FORWARD", *rule], required=False)
    if present.returncode == 1:
        command(["/usr/sbin/iptables", "-w", "2", "-I", "FORWARD", "1", *rule])
    elif present.returncode:
        raise ValueError("resource_network_forwarding_unavailable")


def release(binding):
    result = command(["/usr/sbin/iptables", "-w", "2", "-S", "FORWARD"])
    for line in result.stdout.decode("utf-8").splitlines():
        values = shlex.split(line)
        if "--comment" not in values:
            continue
        comment = values[values.index("--comment") + 1]
        match = re.fullmatch(r"cloudhelm:(resource-[0-9a-f]{40}):([0-9a-f]{64}):([0-9]+)", comment)
        if match is None or match[1] != binding:
            continue
        interface = "br-" + match[2][:12]
        if values != ["-A", "FORWARD", *_rule(interface, comment)]:
            raise ValueError("resource_network_owned_rule_changed")
        command(["/usr/sbin/iptables", "-w", "2", "-D", "FORWARD", *_rule(interface, comment)])
        path = Path("/sys/class/net") / interface
        if path.exists():
            if (path / "ifindex").read_text(encoding="utf-8").strip() != match[3] or not (path / "bridge").is_dir():
                raise ValueError("resource_network_interface_identity_changed")
            command(["/usr/sbin/ip", "link", "delete", "dev", interface])
