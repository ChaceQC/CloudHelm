"""Read-only, fail-closed physical evidence for the dedicated first-install boundary."""

import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

from . import closeout_daemons
from .ledger import RemoteError


def _processes(group, mount, docker_root, unrelated_socket):
    root = Path("/sys/fs/cgroup")
    if not (root / "cgroup.controllers").is_file() or not group.is_relative_to(root):
        raise RemoteError("remote_closeout_cgroup_unverified")
    expected = "0::/" + str(group.relative_to(root))
    mounts = [line.split(" - ", 1) for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines()]
    proc = [item for item in mounts if len(item) == 2 and item[0].split()[4] == "/proc" and item[1].split()[0] == "proc"]
    if len(proc) != 1 or any(option.startswith("hidepid=") and option != "hidepid=0"
            for option in (proc[0][0].split()[5] + "," + proc[0][1].split()[2]).split(",")):
        raise RemoteError("remote_closeout_process_visibility_unverified")
    if group.exists():
        def fail(error):
            raise error

        for current, _, _ in os.walk(group, onerror=fail, followlinks=False):
            if (Path(current) / "cgroup.procs").read_text(encoding="utf-8").strip():
                raise RemoteError("remote_closeout_processes_present")
    count, daemons = 0, {}
    for process in Path("/proc").iterdir():
        if not process.name.isdecimal():
            continue
        try:
            groups = (process / "cgroup").read_text(encoding="utf-8").splitlines()
            name = (process / "comm").read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        count += 1
        if any(line == expected or line.startswith(expected + "/") for line in groups):
            raise RemoteError("remote_closeout_processes_present")
        if name == "dockerd" or name.startswith("containerd"):
            if unrelated_socket is None:
                raise RemoteError("remote_closeout_daemon_scope_unverified")
            daemons[int(process.name)] = name
    scope = closeout_daemons.verify(unrelated_socket, mount, docker_root, daemons) if daemons else None
    return count, scope


def _daemon(resources, unit, docker_root):
    if not isinstance(unit, str) or not re.fullmatch(r"[A-Za-z0-9_:.-]+\.service", unit) or unit.startswith("-"):
        raise RemoteError("remote_closeout_service_unverified")
    result = subprocess.run(["systemctl", "show", "--property=LoadState,ActiveState,UnitFileState,MainPID,Slice,ExecStart",
        "--", unit], capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    if (result.returncode or fields.get("LoadState") not in {"loaded", "masked"}
            or fields.get("ActiveState") != "inactive" or fields.get("UnitFileState") not in {"disabled", "masked"}
            or fields.get("MainPID") != "0" or fields.get("Slice") != resources.parent):
        raise RemoteError("remote_closeout_service_unverified")
    start = fields.get("ExecStart", "")
    if start.count("argv[]=") != 1:
        raise RemoteError("remote_closeout_daemon_identity_unverified")
    arguments = shlex.split(start.split("argv[]=", 1)[1].split(" ; ", 1)[0])
    executable = Path(arguments[0]) if arguments else Path("")
    if (not arguments or not executable.is_absolute() or executable.resolve(strict=True).name != "dockerd"
            or not executable.is_file() or not os.access(executable, os.X_OK)):
        raise RemoteError("remote_closeout_daemon_identity_unverified")
    values = {key: [] for key in ("--data-root", "--pidfile")}
    for index, argument in enumerate(arguments):
        for key in values:
            if argument.startswith(key + "="):
                values[key].append(argument[len(key) + 1:])
            elif argument == key and index + 1 < len(arguments):
                values[key].append(arguments[index + 1])
    if (any(len(value) != 1 or not Path(value[0]).is_absolute() for value in values.values())
            or Path(values["--data-root"][0]).resolve(strict=True) != docker_root
            or Path(values["--pidfile"][0]).resolve(strict=False) != resources.daemon_pid_file.resolve(strict=False)):
        raise RemoteError("remote_closeout_daemon_identity_unverified")
    pid_file = resources.daemon_pid_file
    if pid_file.is_symlink():
        raise RemoteError("remote_closeout_daemon_pid_unverified")
    if pid_file.exists():
        value = pid_file.stat()
        if not stat.S_ISREG(value.st_mode) or value.st_size > 32:
            raise RemoteError("remote_closeout_daemon_pid_unverified")
        raw = pid_file.read_text(encoding="utf-8").strip()
        if not raw.isdecimal() or int(raw) <= 0 or Path("/proc", raw).exists():
            raise RemoteError("remote_closeout_daemon_pid_unverified")
    return {"unit": unit, "load_state": fields["LoadState"], "active_state": fields["ActiveState"],
        "unit_file_state": fields["UnitFileState"], "main_pid": 0, "pid_file_present": pid_file.exists()}


def collect(ledger, resources, docker_root, unit, disk_cap, unrelated_socket=None):
    try:
        mount = resources.mount
        root = Path(docker_root).resolve(strict=True)
        group = resources.group
        if (not mount.is_mount() or not ledger.directory.resolve().is_relative_to(mount)
                or not root.is_relative_to(mount) or not root.is_dir()
                or resources.parent != group.name or not group.name.endswith(".slice")):
            raise RemoteError("remote_closeout_boundary_unverified")
        device = mount.stat().st_dev
        if any(path.stat().st_dev != device for path in (ledger.directory, ledger.directory / "ledger.sqlite3", root)):
            raise RemoteError("remote_closeout_filesystem_unverified")
        for name in ("ledger.sqlite3-wal", "ledger.sqlite3-shm"):
            path = ledger.directory / name
            if path.exists() and (path.is_symlink() or path.stat().st_dev != device):
                raise RemoteError("remote_closeout_filesystem_unverified")
        filesystem = os.statvfs(mount)
        total = filesystem.f_blocks * filesystem.f_frsize
        if total <= 0 or total > disk_cap:
            raise RemoteError("remote_closeout_filesystem_unverified")
        for name in ("containers", "volumes"):
            directory = root / name
            if directory.is_symlink() or not directory.is_dir() or directory.stat().st_dev != device:
                raise RemoteError("remote_closeout_runtime_objects_unverified")
            for entry in directory.iterdir():
                value = entry.lstat()
                if name == "volumes" and value.st_dev == device:
                    if entry.name == "metadata.db" and stat.S_ISREG(value.st_mode):
                        continue
                    if entry.name == "backingFsBlockDev" and stat.S_ISBLK(value.st_mode) and value.st_rdev == device:
                        continue
                raise RemoteError("remote_closeout_runtime_objects_present")
        daemon = _daemon(resources, unit, root)
        count, scope = _processes(group, mount, root, unrelated_socket)
        evidence = {"mount": str(mount), "device": device, "filesystem_bytes": total, "docker_root": str(root),
            "containers_empty": True, "business_volumes_empty": True, "cgroup": str(group),
            "cgroup_present": group.exists(), "processes_scanned": count, "daemon": daemon}
        if scope is not None:
            evidence["unrelated_docker_scope"] = scope
        return evidence
    except (OSError, ValueError, subprocess.SubprocessError):
        raise RemoteError("remote_closeout_physical_evidence_unavailable") from None
