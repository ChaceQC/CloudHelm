"""Scoped source freeze by one file-service lock plus observed read-only readers."""

import json
import os
import re
import signal
import subprocess
import time
from contextlib import contextmanager
from datetime import UTC, datetime

import rfc8785

from modules.workspaces.candidate_writers import overlaps, process_start_ticks, verify_kernel_reader
from modules.workspaces.git_process import _collect
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p1.workspace_candidates import WorkspaceFreezeProof, WorkspaceWriterScope
from packages.contracts.p1.workspace_git import content_digest

_INSPECT = (
    '{"id":{{json .Id}},"status":{{json .State.Status}},"pid":{{json .State.Pid}},'
    '"mounts":{{json .Mounts}},"privileged":{{json .HostConfig.Privileged}},'
    '"cap_add":{{json .HostConfig.CapAdd}},"devices":{{json .HostConfig.Devices}},'
    '"pid_mode":{{json .HostConfig.PidMode}},'
    '"operation":{{json (index .Config.Labels "cloudhelm.operation_id")}},'
    '"scope":{{json (index .Config.Labels "cloudhelm.scope")}},'
    '"method":{{json (index .Config.Labels "cloudhelm.method")}}}'
)
_ENVIRONMENT = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                "HOME": "/nonexistent", "DOCKER_CONFIG": "/nonexistent"}


def _docker(arguments):
    """Only fixed local read operations; never collect Env, args or diagnostics."""
    process = None
    try:
        process = subprocess.Popen(
            ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=_ENVIRONMENT, cwd="/", start_new_session=True,
        )
        output = _collect(process, 2 * 1024 * 1024, time.monotonic() + 10)
        if process.wait(timeout=1) != 0:
            raise WorkspaceFileError("workspace_docker_inventory_unavailable")
        return output.decode("utf-8")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise WorkspaceFileError("workspace_docker_inventory_unavailable") from None
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    raise WorkspaceFileError("workspace_inventory_process_stop_unconfirmed") from None
            process.stdout.close()


def _container_ids():
    ids = tuple(sorted(_docker(("ps", "--all", "--quiet", "--no-trunc")).split()))
    if len(ids) > 256 or len(ids) != len(set(ids)) or any(re.fullmatch(r"[0-9a-f]{64}", item) is None for item in ids):
        raise WorkspaceFileError("workspace_docker_inventory_invalid")
    return ids


def _inventory():
    ids = _container_ids()
    try:
        observations = {}

        def inspect(container_id):
            try:
                value = json.loads(_docker(("inspect", "--format", _INSPECT, container_id)))
            except WorkspaceFileError:
                if container_id not in _container_ids():
                    return  # An unrelated finished execution may disappear.
                raise
            if value["id"] != container_id:
                raise WorkspaceFileError("workspace_docker_inventory_invalid")
            observations[container_id] = value

        for item in ids:
            inspect(item)
        for item in set(_container_ids()) - set(ids):
            inspect(item)
        return tuple(observations[key] for key in sorted(observations))
    except (ValueError, TypeError, KeyError):
        raise WorkspaceFileError("workspace_docker_inventory_invalid") from None


def _verify_readers(files, scope):
    source = os.readlink(f"/proc/self/fd/{files}")
    readers = {item.container_id: item for item in scope.readers}
    found, relevant = set(), []
    inventory = _inventory()
    try:
        for container in inventory:
            mounts = [item for item in container["mounts"]
                      if item.get("Source", "").startswith("/") and overlaps(os.path.realpath(item["Source"]), source)]
            if not mounts:
                if container["id"] in readers:
                    raise WorkspaceFileError("workspace_reader_mount_mismatch")
                continue
            if container["privileged"] or container["devices"] or container["pid_mode"] == "host":
                raise WorkspaceFileError("workspace_writer_topology_unsupported")
            relevant.append(container)
            registered = readers.get(container["id"])
            if registered is None or any(item.get("RW") is not False for item in mounts):
                raise WorkspaceFileError("workspace_unknown_writer")
            if (len(mounts) != 1 or mounts[0]["Type"] != "bind" or container["cap_add"]
                    or mounts[0]["Source"] != source or mounts[0]["Destination"] != registered.mount_destination
                    or (container["operation"], container["scope"], container["method"]) != (
                        registered.operation_id, registered.scope, registered.method)):
                raise WorkspaceFileError("workspace_reader_mount_mismatch")
            if container["status"] in {"running", "paused"}:
                if type(container["pid"]) is not int or container["pid"] <= 0:
                    raise WorkspaceFileError("workspace_reader_identity_unconfirmed")
                verify_kernel_reader(container["pid"], registered.mount_destination)
            elif container["status"] not in {"created", "exited", "dead"}:
                raise WorkspaceFileError("workspace_reader_identity_unconfirmed")
            found.add(container["id"])
        if found != set(readers):
            raise WorkspaceFileError("workspace_reader_identity_unconfirmed")
    except (TypeError, KeyError, OSError):
        raise WorkspaceFileError("workspace_docker_inventory_invalid") from None
    return content_digest(rfc8785.dumps(relevant))


class _FrozenWorkspace:
    def __init__(self, owner, root, files, scope, proof):
        self.owner, self.active = owner, True
        self.root = (os.fstat(root).st_dev, os.fstat(root).st_ino)
        self.files = (os.fstat(files).st_dev, os.fstat(files).st_ino)
        self.scope, self.proof = scope, proof


class CandidateFreezeController:
    """The registry and all file/Runner admission share the caller's root lock.

    Only the service process can write source; Runner containers bind it read-only.
    Empty reader registrations still perform the real Docker inventory. General
    writable Runner views and human editors require a future stop/handoff protocol.
    """

    def __init__(self, resolve_scope):
        if not callable(resolve_scope):
            raise WorkspaceFileError("workspace_writer_resolver_required")
        self._resolver = resolve_scope

    def _current(self, scope_id, binding):
        try:
            scope = self._resolver(scope_id)
        except LookupError:
            raise WorkspaceFileError("workspace_writer_scope_unregistered") from None
        if type(scope) is not WorkspaceWriterScope:
            raise WorkspaceFileError("workspace_writer_scope_invalid")
        try:
            scope = WorkspaceWriterScope.model_validate(scope.model_dump())
        except ValueError:
            raise WorkspaceFileError("workspace_writer_scope_invalid") from None
        if scope.scope_id != scope_id or scope.binding != binding:
            raise WorkspaceFileError("workspace_writer_scope_mismatch")
        if scope.service_pid != os.getpid() or scope.service_start_ticks != process_start_ticks(os.getpid()):
            raise WorkspaceFileError("workspace_writer_identity_mismatch")
        return scope

    @contextmanager
    def freeze(self, root, files, binding, scope_id):
        scope = self._current(scope_id, binding)
        observed = _verify_readers(files, scope)
        proof = WorkspaceFreezeProof(
            runtime_scope_id=scope_id, writer_scope_digest=content_digest(rfc8785.dumps(scope.model_dump(mode="json"))),
            service_instance_id=scope.service_instance_id, service_pid=scope.service_pid,
            service_start_ticks=scope.service_start_ticks,
            reader_container_ids=tuple(sorted(item.container_id for item in scope.readers)),
            observed_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
        handle = _FrozenWorkspace(self, root, files, scope, proof)
        handle.inventory_digest = observed
        try:
            yield handle
        finally:
            handle.active = False

    def validate(self, handle, root, files):
        if (type(handle) is not _FrozenWorkspace or handle.owner is not self or not handle.active
                or handle.root != (os.fstat(root).st_dev, os.fstat(root).st_ino)
                or handle.files != (os.fstat(files).st_dev, os.fstat(files).st_ino)):
            raise WorkspaceFileError("workspace_freeze_scope_invalid")
        if self._current(handle.scope.scope_id, handle.scope.binding) != handle.scope:
            raise WorkspaceFileError("workspace_writer_scope_mismatch")
        if _verify_readers(files, handle.scope) != handle.inventory_digest:
            raise WorkspaceFileError("workspace_docker_inventory_changed")
