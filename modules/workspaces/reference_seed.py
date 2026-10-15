"""Fixed reference-r1 raw objects; never load seed Git config or execute its code."""

import hashlib
import json
import os
import stat
import zlib
from contextlib import contextmanager
from pathlib import PurePosixPath

from modules.workspaces.git_objects import _read_object, read_commit_files
from modules.workspaces.safe_paths import WorkspaceFileError, directory_at, exists_at, read_regular, write_new_file
from packages.contracts.p1.workspace_git import MAX_FILE_BYTES, RegisteredGitSource, content_digest, workspace_path

REFERENCE_COMMIT = "6dd8b605a5cc4b7b641cc0f9b4f2633614c6e757"
REFERENCE_REVISION = "p0-reference-input-set-r1"
REFERENCE_PREFIX = "examples/standalone-project"
REFERENCE_INPUT_SET = "docs/acceptance/reference/input-set-r1.json"
REFERENCE_INPUT_DIGEST = "sha256:119053f06e8adb7f56a19b1c7622e5f9249f40697029a6a3c673f7ebc88e43d0"
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@contextmanager
def _seed_root(path):
    parsed = PurePosixPath(os.fspath(path))
    if not parsed.is_absolute() or ".." in parsed.parts:
        raise WorkspaceFileError("reference_seed_path_invalid")
    descriptor = os.open("/", _DIRECTORY)
    try:
        for part in parsed.parts[1:]:
            following = os.open(part, _DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        yield descriptor
    except OSError:
        raise WorkspaceFileError("reference_seed_unavailable") from None
    finally:
        os.close(descriptor)


def _manifest(root: int) -> dict[str, str]:
    directory, pinned, reader = os.dup(root), -1, -1
    try:
        parts = workspace_path(REFERENCE_INPUT_SET).split("/")
        for part in parts[:-1]:
            following = os.open(part, _DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = following
        pinned = os.open(parts[-1], os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
        before = os.fstat(pinned)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 65536 or before.st_nlink != 1:
            raise WorkspaceFileError("reference_input_set_unsupported")
        reader = os.open(f"/proc/self/fd/{pinned}", os.O_RDONLY | os.O_CLOEXEC)
        with os.fdopen(os.dup(reader), "rb") as stream:
            data = stream.read(65537)
        after = os.fstat(reader)
        shape = lambda item: (item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if len(data) != before.st_size or shape(before) != shape(after):
            raise WorkspaceFileError("reference_input_set_changed")
        if "sha256:" + hashlib.sha256(data).hexdigest() != REFERENCE_INPUT_DIGEST:
            raise WorkspaceFileError("reference_input_set_mismatch")
        document = json.loads(data)
        if document["revision"] != REFERENCE_REVISION or document["source_commit"] != REFERENCE_COMMIT:
            raise WorkspaceFileError("reference_input_set_mismatch")
        files = {item["path"][len(REFERENCE_PREFIX) + 1:]: item["sha256"] for item in document["files"]
                 if item["path"].startswith(REFERENCE_PREFIX + "/")}
        if len(files) != 32 or len(document["files"]) != 36:
            raise WorkspaceFileError("reference_input_set_mismatch")
        return files
    except WorkspaceFileError:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        raise WorkspaceFileError("reference_input_set_unavailable") from None
    finally:
        for descriptor in (reader, pinned, directory):
            if descriptor >= 0:
                os.close(descriptor)


def _check_seed_objects(directory: int) -> None:
    count, total = [0], [0]

    def visit(parent: int, prefix: str, depth: int):
        if depth > 4:
            raise WorkspaceFileError("reference_objects_unsupported")
        for name in os.listdir(parent):
            path = f"{prefix}/{name}" if prefix else name
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            count[0] += 1
            if count[0] > 16384 or path in {"info/alternates", "info/http-alternates"} or name.endswith(".promisor"):
                raise WorkspaceFileError("reference_objects_unsupported")
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, _DIRECTORY, dir_fd=parent)
                try:
                    visit(child, path, depth + 1)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                total[0] += info.st_size
                if total[0] > 512 * 1024 * 1024:
                    raise WorkspaceFileError("reference_objects_limit_exceeded")
            else:
                raise WorkspaceFileError("reference_objects_unsupported")

    visit(directory, "", 0)


@contextmanager
def reference_objects(repository):
    """Trusted local checkout only; DrvFs mode bits are not a private-root claim."""
    with _seed_root(repository) as root:
        expected = _manifest(root)
        metadata = objects = -1
        try:
            metadata = os.open(".git", _DIRECTORY, dir_fd=root)
            objects = os.open("objects", _DIRECTORY, dir_fd=metadata)
            _check_seed_objects(objects)
            yield objects, expected
        except OSError:
            raise WorkspaceFileError("reference_objects_unavailable") from None
        finally:
            for descriptor in (objects, metadata):
                if descriptor >= 0:
                    os.close(descriptor)


def initialize_bare(directory: int, source: RegisteredGitSource) -> None:
    write_new_file(directory, "config", b"[core]\nrepositoryformatversion = 0\nfilemode = true\nbare = true\n")
    write_new_file(directory, "HEAD", f"ref: {source.target_branch}\n".encode("utf-8"))
    for path in ("objects", "refs/heads"):
        with directory_at(directory, path, create=True):
            pass


def _write_object(directory: int, kind: str, data: bytes) -> str:
    raw = f"{kind} {len(data)}\0".encode("ascii") + data
    oid = hashlib.sha1(raw).hexdigest()
    compressed = zlib.compress(raw)
    with directory_at(directory, "objects/" + oid[:2], create=True) as objects:
        if exists_at(objects, oid[2:]):
            if read_regular(objects, oid[2:], len(compressed)) != compressed:
                raise WorkspaceFileError("source_import_object_conflict")
        else:
            write_new_file(objects, oid[2:], compressed)
    return oid


def _write_tree(directory: int, files) -> str:
    root = {}
    for entry in files:
        node, parts = root, entry.path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = entry

    def emit(node):
        entries = []
        ordered = sorted(node.items(), key=lambda item: (item[0] + ("/" if isinstance(item[1], dict) else "")).encode("utf-8"))
        for name, value in ordered:
            mode, oid = ("40000", emit(value)) if isinstance(value, dict) else (value.mode, value.blob_id)
            entries.append(mode.encode("ascii") + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(oid))
        return _write_object(directory, "tree", b"".join(entries))

    return emit(root)


def prepare_reference(directory: int, seed_repository, source: RegisteredGitSource, deadline: float):
    initialize_bare(directory, source)
    with reference_objects(seed_repository) as (objects, expected):
        tree_id, files = read_commit_files(directory, REFERENCE_COMMIT, REFERENCE_PREFIX, deadline,
                                           object_directory=objects)
        if {entry.path for entry in files} != set(expected):
            raise WorkspaceFileError("reference_source_file_set_mismatch")
        if any(entry.content_digest != "sha256:" + expected[entry.path] for entry in files):
            raise WorkspaceFileError("reference_source_digest_mismatch")
        for entry in files:
            data = _read_object(directory, "blob", entry.blob_id, MAX_FILE_BYTES, deadline, object_directory=objects)
            if len(data) != entry.size_bytes or content_digest(data) != entry.content_digest:
                raise WorkspaceFileError("reference_source_digest_mismatch")
            if _write_object(directory, "blob", data) != entry.blob_id:
                raise WorkspaceFileError("source_import_object_conflict")
    if _write_tree(directory, files) != tree_id:
        raise WorkspaceFileError("source_import_tree_mismatch")
    commit_data = (
        f"tree {tree_id}\nauthor CloudHelm reference import <source-import@cloudhelm.invalid> 0 +0000\n"
        "committer CloudHelm reference import <source-import@cloudhelm.invalid> 0 +0000\n\n"
        f"Import fixed reference r1\nseed-commit {REFERENCE_COMMIT}\nseed-prefix {REFERENCE_PREFIX}\n"
        f"input-set {REFERENCE_INPUT_DIGEST}\n"
    ).encode("utf-8")
    commit = _write_object(directory, "commit", commit_data)
    write_new_file(directory, source.target_branch, (commit + "\n").encode("ascii"))
    return commit, tree_id, files
