"""Closed system-Git execution and service-owned bare metadata checks."""

import configparser
import os
import re
import selectors
import signal
import stat
import subprocess
import time

from modules.workspaces.safe_paths import (
    WorkspaceFileError, _trusted, directory_at, read_regular,
)
from packages.contracts.p1.workspace_git import git_branch_ref

_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
    "HOME": "/nonexistent", "XDG_CONFIG_HOME": "/nonexistent",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1",
    "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
}
_OPTIONS = (
    "--no-pager", "--no-replace-objects",
    "-c", "core.hooksPath=/dev/null", "-c", "core.attributesFile=/dev/null",
    "-c", "core.fsmonitor=false", "-c", "diff.external=",
    "-c", "credential.helper=", "-c", "protocol.allow=never",
)
_FORBIDDEN = {
    "commondir", "gitdir", "config.worktree", "worktrees", "shallow",
    "info/grafts", "info/attributes", "objects/info/alternates",
    "objects/info/http-alternates", "refs/replace",
}


def validate_bare_metadata(directory: int, object_format: str) -> None:
    """Never ask Git to parse an unchecked local config/include chain."""
    expected = {"core": {"repositoryformatversion": "0", "filemode": "true", "bare": "true"}}
    if object_format == "sha256":
        expected["core"]["repositoryformatversion"] = "1"
        expected["extensions"] = {"objectformat": "sha256"}
    try:
        parser = configparser.ConfigParser(interpolation=None, strict=True)
        parser.read_string(read_regular(directory, "config", 16384).decode("utf-8"))
        actual = {section: dict(parser[section]) for section in parser.sections()}
        if parser.defaults() or actual != expected:
            raise WorkspaceFileError("git_config_unsupported")
    except (UnicodeError, configparser.Error):
        raise WorkspaceFileError("git_config_unsupported") from None
    visited = [0]

    def visit(parent: int, prefix: str, depth: int) -> None:
        if depth > 64:
            raise WorkspaceFileError("git_metadata_limit_exceeded")
        for name in os.listdir(parent):
            visited[0] += 1
            if visited[0] > 100000:
                raise WorkspaceFileError("git_metadata_limit_exceeded")
            path = f"{prefix}/{name}" if prefix else name
            if path in _FORBIDDEN or name.endswith(".lock"):
                raise WorkspaceFileError("git_metadata_unsupported")
            if prefix == "hooks" and not name.endswith(".sample"):
                raise WorkspaceFileError("git_hooks_unsupported")
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            is_directory = stat.S_ISDIR(info.st_mode)
            _trusted(info, directory=is_directory, device=os.fstat(directory).st_dev)
            if is_directory:
                with directory_at(parent, name) as child:
                    visit(child, path, depth + 1)

    try:
        visit(directory, "", 0)
    except OSError:
        raise WorkspaceFileError("git_metadata_unavailable") from None


def _collect(process: subprocess.Popen, limit: int, deadline: float) -> bytes:
    output = bytearray()
    os.set_blocking(process.stdout.fileno(), False)
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WorkspaceFileError("git_timeout")
            if not selector.select(remaining):
                raise WorkspaceFileError("git_timeout")
            block = os.read(process.stdout.fileno(), min(65536, limit + 1 - len(output)))
            if not block:
                return bytes(output)
            output.extend(block)
            if len(output) > limit:
                raise WorkspaceFileError("git_output_limit_exceeded")


def _allowed_arguments(arguments: tuple[str, ...]) -> bool:
    oid = lambda value: isinstance(value, str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value)
    if len(arguments) == 3 and arguments[0] == "cat-file":
        return arguments[1] in {"commit", "tree", "blob"} and bool(oid(arguments[2]))
    if len(arguments) == 4 and arguments[:2] == ("merge-base", "--is-ancestor"):
        return bool(oid(arguments[2]) and oid(arguments[3]))
    branch = None
    if len(arguments) == 3 and arguments[:2] == ("symbolic-ref", "--quiet"):
        branch = arguments[2]
    if (len(arguments) == 4 and arguments[:3] == ("rev-parse", "--verify", "--end-of-options")
            and arguments[3].endswith("^{commit}")):
        branch = arguments[3][:-9]
    if branch is not None:
        try:
            git_branch_ref(branch)
            return True
        except ValueError:
            return False
    return False


def run_git(directory: int, arguments: tuple[str, ...], *, limit: int, deadline: float,
            accepted_codes: tuple[int, ...] = (0,), object_directory: int | None = None) -> tuple[int, bytes]:
    """Internal fixed callers only; no public arbitrary command adapter."""
    if time.monotonic() >= deadline:
        raise WorkspaceFileError("git_timeout")
    if not _allowed_arguments(arguments):
        raise WorkspaceFileError("git_operation_unsupported")
    environment, descriptors = _ENVIRONMENT, (directory,)
    if object_directory is not None:
        if arguments[0] != "cat-file" or not stat.S_ISDIR(os.fstat(object_directory).st_mode):
            raise WorkspaceFileError("git_seed_operation_unsupported")
        environment = {**_ENVIRONMENT, "GIT_OBJECT_DIRECTORY": f"/proc/self/fd/{object_directory}",
                       "GIT_ALTERNATE_OBJECT_DIRECTORIES": "", "GIT_NO_LAZY_FETCH": "1"}
        descriptors = (directory, object_directory)
    process = None
    try:
        process = subprocess.Popen(
            ["/usr/bin/git", *_OPTIONS, f"--git-dir=/proc/self/fd/{directory}", *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=environment, cwd="/", pass_fds=descriptors, start_new_session=True,
        )
        output = _collect(process, limit, deadline)
        code = process.wait(timeout=max(0.001, deadline - time.monotonic()))
        if code not in accepted_codes:
            raise WorkspaceFileError("git_object_unavailable")
        return code, output
    except subprocess.TimeoutExpired:
        raise WorkspaceFileError("git_timeout") from None
    except OSError:
        raise WorkspaceFileError("git_unavailable") from None
    finally:
        if process is not None:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    raise WorkspaceFileError("git_stop_unconfirmed") from None
            process.stdout.close()
