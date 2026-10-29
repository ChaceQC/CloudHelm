"""Small, secret-free operation fence and physical stop observations."""

import json
import os
import secrets
import stat
from pathlib import Path

from .toolchain import ProbeFailure


def write(path: Path, value: dict):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temporary = path.with_name("." + path.name + "." + secrets.token_hex(8) + ".next")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def read(path: Path) -> dict:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077
                or info.st_nlink != 1 or info.st_size > 65536):
            raise ProbeFailure("candidate_preview_journal_invalid")
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ProbeFailure("candidate_preview_journal_invalid")
    return value
