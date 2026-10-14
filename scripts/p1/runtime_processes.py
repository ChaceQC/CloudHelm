"""Bounded real API/worker processes sharing a caller-owned P1 database fixture."""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator
from uuid import uuid4

import httpx

from modules.workflow.version import APPLICATION_NAME, APPLICATION_VERSION
from scripts.p1.database_fixture import DatabaseFixture

_ROOT = Path(__file__).resolve().parents[2]
_PYTHON = _ROOT / ".venv/bin/python"
_LOCK_ROOT = Path("/home/cloudhelm/.local/state/cloudhelm/worker-locks")
_ACTIVE: dict[str, set[subprocess.Popen]] = {}
_LIFECYCLE_LOCK = threading.Lock()
READY_TIMEOUT = 30.0
EXIT_TIMEOUT = 30.0


class RuntimeProcessError(RuntimeError):
    """Fixed failure category; no child output, HTTP body or credential is attached."""


def _environment(fixture: DatabaseFixture, role: str) -> dict[str, str]:
    names = ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "WSL_DISTRO_NAME")
    environment = {name: os.environ[name] for name in names if name in os.environ}
    environment.update(fixture.environment_for(role))
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    return environment


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=EXIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            raise RuntimeProcessError("runtime_process_stop_unconfirmed") from None
        raise RuntimeProcessError("runtime_process_shutdown_timeout") from None


def _cleanup_worker_lock(fixture: DatabaseFixture) -> None:
    if _ACTIVE.get(fixture.project_name) or fixture.baseline is None:
        return
    import fcntl

    filename = hashlib.sha256(fixture.baseline.installation_id.encode("utf-8")).hexdigest() + ".lock"
    path = _LOCK_ROOT / filename
    if not path.exists():
        return
    if path.is_symlink() or path.resolve().parent != _LOCK_ROOT.resolve():
        raise RuntimeProcessError("runtime_lock_cleanup_path_invalid")
    descriptor = os.open(path, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        record = os.fstat(descriptor)
        if not stat.S_ISREG(record.st_mode) or record.st_uid != os.getuid():
            raise RuntimeProcessError("runtime_lock_cleanup_identity_invalid")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeProcessError("runtime_lock_still_held") from None
        current = path.lstat()
        if (current.st_dev, current.st_ino) != (record.st_dev, record.st_ino):
            raise RuntimeProcessError("runtime_lock_cleanup_identity_changed")
        path.unlink()
    finally:
        os.close(descriptor)


@contextmanager
def _process(fixture: DatabaseFixture, role: str, module: str, arguments: list[str],
             *, capture_stdout: bool = False) -> Iterator[subprocess.Popen]:
    if fixture.baseline is None or not _PYTHON.is_file():
        raise RuntimeProcessError("runtime_fixture_or_interpreter_unavailable")
    try:
        with _LIFECYCLE_LOCK:
            process = subprocess.Popen(
                [str(_PYTHON), "-B", "-m", module, *arguments], cwd=_ROOT,
                env=_environment(fixture, role), stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture_stdout else subprocess.DEVNULL, start_new_session=True,
            )
            _ACTIVE.setdefault(fixture.project_name, set()).add(process)
    except OSError:
        raise RuntimeProcessError("runtime_process_start_failed") from None
    try:
        yield process
    finally:
        try:
            _stop(process)
        except OSError:
            raise RuntimeProcessError("runtime_process_signal_failed") from None
        finally:
            try:
                if process.stdout is not None:
                    process.stdout.close()
                if process.poll() is not None:
                    with _LIFECYCLE_LOCK:
                        _ACTIVE[fixture.project_name].discard(process)
                        _cleanup_worker_lock(fixture)
            except OSError:
                raise RuntimeProcessError("runtime_process_cleanup_failed") from None


@dataclass(slots=True, repr=False)
class WorkerProcess:
    process: subprocess.Popen
    installation_id: str
    _buffer: bytes = field(default=b"", repr=False)
    _received: int = 0

    def _event(self, timeout: float) -> dict[str, object]:
        if self.process.stdout is None:
            raise RuntimeProcessError("worker_status_pipe_missing")
        descriptor = self.process.stdout.fileno()
        os.set_blocking(descriptor, False)
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(descriptor, selectors.EVENT_READ)
            while time.monotonic() < deadline:
                if b"\n" in self._buffer:
                    line, self._buffer = self._buffer.split(b"\n", 1)
                    try:
                        event = json.loads(line.decode("utf-8"))
                    except (ValueError, UnicodeError):
                        raise RuntimeProcessError("worker_status_invalid") from None
                    if not isinstance(event, dict) or event.get("status") not in {
                        "ready", "rejected", "failed", "shutdown_requested"
                    }:
                        raise RuntimeProcessError("worker_status_invalid")
                    return event
                if not selector.select(min(0.1, max(0.0, deadline - time.monotonic()))):
                    continue
                chunk = os.read(descriptor, 4096)
                if not chunk:
                    raise RuntimeProcessError("worker_exited_before_status")
                self._received += len(chunk)
                self._buffer += chunk
                if self._received > 16384 or len(self._buffer) > 8192:
                    raise RuntimeProcessError("worker_status_output_exceeded")
        raise RuntimeProcessError("worker_ready_timeout")

    def wait_ready(self, timeout: float = READY_TIMEOUT) -> None:
        event = self._event(timeout)
        if (event.get("status") != "ready" or event.get("pid") != self.process.pid
                or event.get("installation_id") != self.installation_id
                or event.get("application_name") != APPLICATION_NAME
                or event.get("application_version") != APPLICATION_VERSION):
            raise RuntimeProcessError("worker_did_not_become_ready")

    def expect_rejected(self, reason: str, timeout: float = READY_TIMEOUT) -> None:
        event = self._event(timeout)
        if event.get("status") != "rejected" or event.get("reason") != reason:
            raise RuntimeProcessError("worker_rejection_mismatch")
        try:
            code = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeProcessError("worker_rejection_did_not_exit") from None
        if code == 0:
            raise RuntimeProcessError("worker_rejection_returned_success")


@contextmanager
def worker_process(fixture: DatabaseFixture) -> Iterator[WorkerProcess]:
    with _process(fixture, "worker", "services.hub-worker", ["--shutdown-grace-seconds", "5"],
                  capture_stdout=True) as process:
        yield WorkerProcess(process, fixture.baseline.installation_id)


@contextmanager
def worker_running(fixture: DatabaseFixture) -> Iterator[WorkerProcess]:
    with worker_process(fixture) as worker:
        worker.wait_ready()
        yield worker
        if worker.process.poll() is not None:
            raise RuntimeProcessError("worker_exited_while_expected_running")
    if worker.process.returncode != 0:
        raise RuntimeProcessError("worker_shutdown_returned_failure")


@dataclass(slots=True, repr=False)
class ApiProcess:
    process: subprocess.Popen
    client: httpx.Client
    socket_path: Path
    _socket_identity: tuple[int, int] | None = field(default=None, repr=False)

    def _capture_socket(self) -> None:
        try:
            current = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(current.st_mode) or current.st_uid != os.getuid():
            raise RuntimeProcessError("api_socket_identity_invalid")
        identity = (current.st_dev, current.st_ino)
        if self._socket_identity is None:
            self._socket_identity = identity
        elif identity != self._socket_identity:
            raise RuntimeProcessError("api_socket_identity_changed")

    def _alive(self) -> bool:
        self._capture_socket()
        try:
            deadline = time.monotonic() + 1.0
            with self.client.stream("GET", "/health/live", timeout=0.5) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 4096 or time.monotonic() > deadline:
                        raise RuntimeProcessError("api_liveness_response_exceeded")
                return (response.status_code == 200 and json.loads(body.decode("utf-8")) == {"status": "alive"}
                        and response.headers.get("X-CloudHelm-API-Schema") == "p1-hub-api-r1")
        except (httpx.HTTPError, ValueError, UnicodeError):
            return False

    def wait_ready(self, timeout: float = READY_TIMEOUT) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._alive():
                return
            if self.process.poll() is not None:
                raise RuntimeProcessError("api_exited_before_ready")
            time.sleep(0.1)
        raise RuntimeProcessError("api_ready_timeout")

    def expect_rejected(self, timeout: float = READY_TIMEOUT) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._alive():
                raise RuntimeProcessError("api_ignored_runtime_gate")
            code = self.process.poll()
            if code is not None:
                if code == 0:
                    raise RuntimeProcessError("api_rejection_returned_success")
                return
            time.sleep(0.1)
        raise RuntimeProcessError("api_rejection_did_not_exit")

    def cleanup_socket(self) -> None:
        if self.process.poll() is None:
            raise RuntimeProcessError("api_socket_cleanup_process_running")
        self._capture_socket()
        if self._socket_identity is not None and self.socket_path.exists():
            self.socket_path.unlink()


@contextmanager
def api_process(fixture: DatabaseFixture, *, instance: str = "api1") -> Iterator[ApiProcess]:
    if not re.fullmatch(r"[a-z0-9_]{1,12}", instance):
        raise RuntimeProcessError("api_instance_name_invalid")
    socket_path = fixture.runtime_dir / f"{instance}-{uuid4().hex[:8]}.sock"
    if (socket_path.parent.resolve() != fixture.runtime_dir.resolve() or socket_path.exists()
            or socket_path.is_symlink() or len(os.fsencode(socket_path)) > 107):
        raise RuntimeProcessError("api_socket_path_unavailable")
    api = None
    try:
        with _process(fixture, "api", "services.hub-api", ["--uds", str(socket_path)]) as process:
            with httpx.Client(transport=httpx.HTTPTransport(uds=str(socket_path)),
                              base_url="http://cloudhelm.test", timeout=5, trust_env=False) as client:
                api = ApiProcess(process, client, socket_path)
                try:
                    yield api
                finally:
                    api._capture_socket()
    finally:
        if api is not None:
            api.cleanup_socket()


@contextmanager
def api_running(fixture: DatabaseFixture, *, instance: str = "api1") -> Iterator[ApiProcess]:
    with api_process(fixture, instance=instance) as api:
        api.wait_ready()
        yield api
        if api.process.poll() is not None:
            raise RuntimeProcessError("api_exited_while_expected_running")
    if api.process.returncode not in {0, -signal.SIGTERM}:
        raise RuntimeProcessError("api_shutdown_returned_failure")
