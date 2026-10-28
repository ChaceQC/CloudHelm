"""Verify the one supported independent Docker/containerd scope during closeout."""

import http.client
import json
import os
import re
import socket
import stat
import struct
from pathlib import Path
from urllib.parse import quote

from .docker_io import _Connection
from .ledger import RemoteError


def _unverified():
    raise RemoteError("remote_closeout_daemon_scope_unverified")


def _peer(sock):
    return struct.unpack("3i", sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))[0]


def _docker_get(endpoint, path):
    connection = _Connection(endpoint)
    try:
        connection.connect()
        peer = _peer(connection.sock)
        connection.request("GET", path)
        response = connection.getresponse()
        data = response.read(2_000_001)
        if response.status != 200 or len(data) > 2_000_000:
            _unverified()
        return peer, json.loads(data)
    finally:
        connection.close()


def _argument(pid, name, *, short=False):
    raw = Path("/proc", str(pid), "cmdline").read_bytes()
    if not raw or len(raw) > 1_000_000:
        _unverified()
    arguments = raw.decode("utf-8").split("\0")
    names = ("--" + name, "-" + name) if short else ("--" + name,)
    values = []
    for index, argument in enumerate(arguments):
        for option in names:
            if argument.startswith(option + "="):
                values.append(argument[len(option) + 1:])
            elif argument == option and index + 1 < len(arguments):
                values.append(arguments[index + 1])
    if len(values) != 1 or not values[0]:
        _unverified()
    return values[0]


def _separate(value, mount, docker_root, device):
    if not isinstance(value, str) or not Path(value).is_absolute():
        _unverified()
    path = Path(value).resolve(strict=True)
    if (path.is_relative_to(mount) or mount.is_relative_to(path)
            or path.is_relative_to(docker_root) or docker_root.is_relative_to(path)
            or path.stat().st_dev == device):
        _unverified()
    return path


def _listener(endpoint):
    inodes = set()
    for line in Path("/proc/net/unix").read_text(encoding="utf-8").splitlines()[1:]:
        fields = line.split(maxsplit=7)
        if len(fields) != 8 or fields[4] != "0001" or not int(fields[3], 16) & 0x10000:
            continue
        path = Path(fields[7])
        if path.is_absolute() and path.resolve(strict=False) == endpoint:
            inodes.add(fields[6])
    if len(inodes) != 1:
        _unverified()
    return "socket:[" + inodes.pop() + "]"


def _active(processes):
    active, zombies = {}, 0
    for pid, name in processes.items():
        state = Path("/proc", str(pid), "stat").read_text(encoding="utf-8").rsplit(") ", 1)[1].split()[0]
        if state == "Z":
            zombies += 1
        else:
            active[pid] = name
    return active, zombies


def _current_processes():
    found = {}
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            name = (process / "comm").read_text(encoding="utf-8").strip()
            if name == "dockerd" or name.startswith("containerd"):
                found[int(process.name)] = name
        except FileNotFoundError:
            continue
    return _active(found)[0]


def _references(pid, device, backing, metadata):
    process = Path("/proc", str(pid))
    for name in ("exe", "cwd", "root"):
        if (process / name).stat().st_dev == device:
            _unverified()
    sockets, has_metadata = set(), False
    for fd in (process / "fd").iterdir():
        try:
            link, value = os.readlink(fd), fd.stat()
        except FileNotFoundError:
            continue
        if (value.st_dev == device or (value.st_dev, value.st_ino) == backing
                or stat.S_ISBLK(value.st_mode) and value.st_rdev == device):
            _unverified()
        if link.startswith("socket:["):
            sockets.add(link)
        if (value.st_dev, value.st_ino) == metadata:
            has_metadata = True
    return sockets, has_metadata


def verify(endpoint, mount, docker_root, processes):
    try:
        if not isinstance(endpoint, str) or not Path(endpoint).is_absolute():
            _unverified()
        active, zombies = _active(processes)
        if not active:
            return {"zombie_processes": zombies}
        dockers = [pid for pid, name in active.items() if name == "dockerd"]
        containers = [pid for pid, name in active.items() if name == "containerd"]
        shims = [pid for pid, name in active.items() if name == "containerd-shim"]
        if len(dockers) != 1 or len(containers) != 1 or not shims or len(active) != 2 + len(shims):
            _unverified()
        docker_pid, containerd_pid = dockers[0], containers[0]
        device = mount.stat().st_dev
        endpoint = _separate(endpoint, mount, docker_root, device)
        if not stat.S_ISSOCK(endpoint.stat().st_mode):
            _unverified()
        listener = _listener(endpoint)
        peer, info = _docker_get(endpoint, "/info")
        listing_peer, listing = _docker_get(endpoint, "/containers/json?all=1")
        if (peer != listing_peer or peer not in (1, docker_pid)
                or peer == 1 and Path("/proc/1/comm").read_text(encoding="utf-8").strip() != "systemd"
                or not isinstance(info, dict) or not isinstance(listing, list)):
            _unverified()
        independent_root = _separate(info["DockerRootDir"], mount, docker_root, device)
        containerd_root = _separate("/var/lib/containerd", mount, docker_root, device)
        containerd_state = _separate("/run/containerd", mount, docker_root, device)
        metadata_path = (containerd_root / "io.containerd.metadata.v1.bolt/meta.db").resolve(strict=True)
        if not metadata_path.is_relative_to(containerd_root):
            _unverified()
        metadata_stat = metadata_path.stat()
        metadata = (metadata_stat.st_dev, metadata_stat.st_ino)
        backing_path = Path("/sys/dev/block", f"{os.major(device)}:{os.minor(device)}", "loop/backing_file")
        backing_name = backing_path.read_text(encoding="utf-8").strip()
        if not backing_name or backing_name.endswith(" (deleted)"):
            _unverified()
        backing_file = Path("/" + backing_name.lstrip("/")).resolve(strict=True)
        backing_stat = backing_file.stat()
        if not stat.S_ISREG(backing_stat.st_mode):
            _unverified()
        backing = (backing_stat.st_dev, backing_stat.st_ino)
        if Path("/proc", str(docker_pid), "exe").resolve(strict=True).name != "dockerd":
            _unverified()
        if Path("/proc", str(containerd_pid), "exe").resolve(strict=True).name != "containerd":
            _unverified()
        address = _argument(docker_pid, "containerd").removeprefix("unix://")
        address = _separate(address, mount, docker_root, device)
        if not stat.S_ISSOCK(address.stat().st_mode):
            _unverified()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(10)
            sock.connect(str(address))
            if _peer(sock) != containerd_pid:
                _unverified()
        ids = set()
        mounts, inspected_volumes = 0, 0
        for item in listing:
            identifier = item["Id"]
            if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{64}", identifier) or identifier in ids:
                _unverified()
            ids.add(identifier)
            for entry in item["Mounts"]:
                if entry["Type"] == "tmpfs" and not entry.get("Source"):
                    continue
                source = entry.get("Source")
                if not source and entry["Type"] == "volume" and item.get("State") in {"created", "exited"}:
                    volume = entry.get("Name")
                    if not isinstance(volume, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", volume):
                        _unverified()
                    volume_peer, detail = _docker_get(endpoint, "/volumes/" + quote(volume, safe=""))
                    if volume_peer != peer or detail["Name"] != volume:
                        _unverified()
                    source = detail["Mountpoint"]
                    inspected_volumes += 1
                source_path = _separate(source, mount, docker_root, device)
                if source_path == backing_file or backing_file.is_relative_to(source_path):
                    _unverified()
                mounts += 1
        docker_sockets, _ = _references(docker_pid, device, backing, metadata)
        _, metadata_open = _references(containerd_pid, device, backing, metadata)
        if listener not in docker_sockets or not metadata_open:
            _unverified()
        shim_ids = set()
        for pid in shims:
            if Path("/proc", str(pid), "exe").resolve(strict=True).name != "containerd-shim-runc-v2":
                _unverified()
            namespace = _argument(pid, "namespace", short=True)
            identifier = _argument(pid, "id", short=True)
            shim_address = _argument(pid, "address", short=True).removeprefix("unix://")
            if (namespace != "moby" or identifier not in ids or identifier in shim_ids or not Path(shim_address).is_absolute()
                    or Path(shim_address).resolve(strict=True) != address):
                _unverified()
            cwd = Path("/proc", str(pid), "cwd").resolve(strict=True)
            if cwd != (containerd_state / "io.containerd.runtime.v2.task/moby" / identifier).resolve(strict=True):
                _unverified()
            _references(pid, device, backing, metadata)
            shim_ids.add(identifier)
        if _listener(endpoint) != listener or _current_processes() != active:
            _unverified()
        return {"docker_pid": docker_pid, "docker_socket_peer_pid": peer, "containerd_pid": containerd_pid,
                "docker_device": independent_root.stat().st_dev, "containerd_root_device": containerd_root.stat().st_dev,
                "containerd_state_device": containerd_state.stat().st_dev, "containers_scanned": len(ids),
                "mount_sources_scanned": mounts, "volumes_inspected": inspected_volumes,
                "shim_processes": len(shims), "zombie_processes": zombies}
    except (OSError, ValueError, TypeError, KeyError, IndexError, http.client.HTTPException, struct.error):
        _unverified()
