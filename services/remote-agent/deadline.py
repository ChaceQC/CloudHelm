"""Supervise one Linux archive step without borrowing process-wide timers."""

import ctypes
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .ledger import RemoteError


def parent_death_signal(parent_pid):
    """Kill this process if its supervising parent disappears, including a fork race."""
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "prctl")
    if os.getppid() != parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


def _kill_group(pid):
    for target in (-pid, pid):
        try:
            os.kill(target, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _supervise(command, payload, end):
    process = subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parents[2], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
    )
    try:
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise RemoteError("remote_archive_deadline_exceeded")
        try:
            output, _ = process.communicate(payload, timeout=remaining)
        except subprocess.TimeoutExpired:
            raise RemoteError("remote_archive_deadline_exceeded") from None
        if time.monotonic() >= end:
            raise RemoteError("remote_archive_deadline_exceeded")
        if process.returncode != 0 or len(output) > 131072:
            raise RemoteError("remote_archive_supervisor_unresolved")
        return output
    finally:
        if process.poll() is None:
            _kill_group(process.pid)
            process.wait()
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def run(end, request):
    """Exec a fresh worker and bound input, execution, and receipt by one deadline.

    Killing the worker's local process group is not evidence that Docker's daemon
    stopped a request; callers must keep that physical result unknown.
    """
    if time.monotonic() >= end:
        raise RemoteError("remote_archive_deadline_exceeded")
    payload = json.dumps(request, separators=(",", ":")).encode("utf-8")
    if len(payload) > 2_000_000:
        raise RemoteError("remote_archive_supervisor_request_too_large")
    output = _supervise(
        [sys.executable, "-B", "-m", "services.remote-agent.archive_worker", str(os.getpid())], payload, end,
    )
    try:
        message = json.loads(output)
        if not isinstance(message, dict) or message.get("ok") is not True:
            raise ValueError("invalid result")
        return message["value"]
    except (KeyError, UnicodeError, ValueError):
        raise RemoteError("remote_archive_supervisor_unresolved") from None
