"""Registered managed sources and verified raw Git objects, without checkout hooks."""

import hashlib
import re
import time
from contextlib import contextmanager

import rfc8785

from modules.workspaces.git_process import run_git, validate_bare_metadata
from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, directory_at
from packages.contracts.p1.workspace_git import (
    MAX_FILE_BYTES, MAX_FILES, MAX_SOURCE_BYTES, GitFile, RegisteredGitSource,
    SourceTree, content_digest, manifest_bytes, workspace_path,
)

_TREE_LIMIT = 2 * 1024 * 1024
_OPERATION_SECONDS = 60
_SAFE_ATTRIBUTES = {"text", "-text", "!text", "text=auto", "eol=lf", "-diff", "-merge"}


def managed_repository_slot(source: RegisteredGitSource) -> str:
    """Trusted importers place a bare here; requests never select host paths."""
    digest = hashlib.sha256(rfc8785.dumps([source.project_id, source.source_id])).hexdigest()
    return "repo-" + digest


def _object_id(value: str, object_format: str) -> str:
    length = 40 if object_format == "sha1" else 64
    if not isinstance(value, str) or re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is None:
        raise WorkspaceFileError("git_object_format_mismatch")
    return value


def _read_object(directory: int, kind: str, oid: str, limit: int, deadline: float,
                 *, object_directory: int | None = None) -> bytes:
    _, data = run_git(directory, ("cat-file", kind, oid), limit=limit, deadline=deadline,
                      object_directory=object_directory)
    algorithm = "sha1" if len(oid) == 40 else "sha256"
    digest = hashlib.new(algorithm, f"{kind} {len(data)}\0".encode("ascii") + data).hexdigest()
    if digest != oid:
        raise WorkspaceFileError("git_object_digest_mismatch")
    return data


def _tree_entries(directory: int, oid: str, deadline: float, *, object_directory: int | None = None):
    data = _read_object(directory, "tree", oid, _TREE_LIMIT, deadline, object_directory=object_directory)
    width, offset, seen, entries = len(oid) // 2, 0, set(), []
    while offset < len(data):
        space, end = data.find(b" ", offset), data.find(b"\0", offset)
        if not offset < space < end or end + 1 + width > len(data):
            raise WorkspaceFileError("git_tree_invalid")
        mode = data[offset:space]
        try:
            name = workspace_path(data[space + 1:end].decode("utf-8"))
        except (ValueError, UnicodeError):
            raise WorkspaceFileError("git_path_unsupported") from None
        if "/" in name or name in seen:
            raise WorkspaceFileError("git_tree_invalid")
        if mode not in {b"40000", b"100644", b"100755"}:
            raise WorkspaceFileError("git_entry_type_unsupported")
        if name.casefold() in {".gitmodules", ".lfsconfig"}:
            raise WorkspaceFileError("git_extension_unsupported")
        child = data[end + 1:end + 1 + width].hex()
        entries.append((mode.decode("ascii"), name, child))
        seen.add(name)
        offset = end + 1 + width
    return entries


def _check_content(path: str, data: bytes) -> None:
    if data[:200].splitlines()[:1] == [b"version https://git-lfs.github.com/spec/v1"]:
        raise WorkspaceFileError("git_lfs_unsupported")
    if path.split("/")[-1].casefold() != ".gitattributes":
        return
    try:
        for raw in data.decode("utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if (len(fields) < 2 or fields[0].startswith("[attr]")
                    or not set(fields[1:]) <= _SAFE_ATTRIBUTES):
                raise WorkspaceFileError("git_attributes_unsupported")
    except UnicodeError:
        raise WorkspaceFileError("git_attributes_unsupported") from None


def _selected_tree(directory: int, root: str, prefix: str, deadline: float,
                   *, object_directory: int | None = None) -> str:
    for part in prefix.split("/") if prefix else ():
        entries = _tree_entries(directory, root, deadline, object_directory=object_directory)
        for mode, name, oid in entries:
            if name == ".gitattributes":
                if mode == "40000":
                    raise WorkspaceFileError("git_attributes_unsupported")
                _check_content(name, _read_object(directory, "blob", oid, MAX_FILE_BYTES, deadline,
                                                 object_directory=object_directory))
        matches = [(mode, oid) for mode, name, oid in entries if name == part]
        if len(matches) != 1 or matches[0][0] != "40000":
            raise WorkspaceFileError("git_source_prefix_unavailable")
        root = matches[0][1]
    return root


def _collect_files(directory: int, tree: str, deadline: float,
                   *, object_directory: int | None = None) -> tuple[GitFile, ...]:
    pending, files, total, visited = [(tree, "")], [], 0, 0
    while pending:
        oid, prefix = pending.pop()
        entries = _tree_entries(directory, oid, deadline, object_directory=object_directory)
        visited += len(entries)
        if visited > MAX_FILES * 2:
            raise WorkspaceFileError("git_tree_limit_exceeded")
        for mode, name, child in entries:
            path = f"{prefix}/{name}" if prefix else name
            try:
                workspace_path(path)
            except (ValueError, UnicodeError):
                raise WorkspaceFileError("git_path_unsupported") from None
            if mode == "40000":
                pending.append((child, path))
                continue
            data = _read_object(directory, "blob", child, MAX_FILE_BYTES, deadline,
                                object_directory=object_directory)
            _check_content(path, data)
            total += len(data)
            if total > MAX_SOURCE_BYTES or len(files) >= MAX_FILES:
                raise WorkspaceFileError("git_source_limit_exceeded")
            files.append(GitFile(path=path, mode=mode, blob_id=child, size_bytes=len(data),
                                 content_digest=content_digest(data)))
    return tuple(sorted(files, key=lambda item: item.path.encode("utf-8")))


def read_commit_files(directory: int, base_commit: str, prefix: str, deadline: float,
                      *, object_directory: int | None = None) -> tuple[str, tuple[GitFile, ...]]:
    """Read only verified raw objects, optionally from a trusted seed object fd."""
    commit = _read_object(directory, "commit", base_commit, 1024 * 1024, deadline,
                          object_directory=object_directory)
    first_line = commit.split(b"\n", 1)[0]
    try:
        if not first_line.startswith(b"tree "):
            raise WorkspaceFileError("git_commit_invalid")
        root = _object_id(first_line[5:].decode("ascii"), "sha1" if len(base_commit) == 40 else "sha256")
    except UnicodeError:
        raise WorkspaceFileError("git_commit_invalid") from None
    tree = _selected_tree(directory, root, prefix, deadline, object_directory=object_directory)
    return tree, _collect_files(directory, tree, deadline, object_directory=object_directory)


def _inspect(directory: int, source: RegisteredGitSource, base_commit: str, deadline: float) -> SourceTree:
    code, _ = run_git(directory, ("symbolic-ref", "--quiet", source.target_branch),
                      limit=256, deadline=deadline, accepted_codes=(0, 1))
    if code == 0:
        raise WorkspaceFileError("git_target_branch_symbolic")
    _, target = run_git(directory, ("rev-parse", "--verify", "--end-of-options",
                                   source.target_branch + "^{commit}"), limit=80, deadline=deadline)
    try:
        tip = _object_id(target.decode("ascii").strip(), source.object_format)
    except UnicodeError:
        raise WorkspaceFileError("git_target_branch_unavailable") from None
    code, _ = run_git(directory, ("merge-base", "--is-ancestor", base_commit, tip),
                      limit=0, deadline=deadline, accepted_codes=(0, 1))
    if code != 0:
        raise WorkspaceFileError("git_commit_outside_target")
    tree, files = read_commit_files(directory, base_commit, source.source_prefix, deadline)
    try:
        return SourceTree(source=source, commit=base_commit, tree_id=tree, files=files,
                          manifest_digest=content_digest(manifest_bytes(files)))
    except ValueError:
        raise WorkspaceFileError("git_source_paths_unsupported") from None


class GitObjectStore:
    """A trusted service registry restored from Hub records, not a public API."""

    def __init__(self, repository_root):
        self._root = PrivateRoot(repository_root)
        self._sources: dict[str, RegisteredGitSource] = {}

    def register_source(self, source: RegisteredGitSource) -> RegisteredGitSource:
        if type(source) is not RegisteredGitSource:
            raise WorkspaceFileError("git_source_invalid")
        try:
            source = RegisteredGitSource.model_validate(source.model_dump())
        except ValueError:
            raise WorkspaceFileError("git_source_invalid") from None
        if source.kind != "managed_bare":
            raise WorkspaceFileError("git_external_source_unsupported")
        with self._root.exclusive() as root:
            existing = self._sources.get(source.project_id)
            if existing is not None and existing != source:
                raise WorkspaceFileError("git_source_already_registered")
            with directory_at(root, managed_repository_slot(source)) as directory:
                validate_bare_metadata(directory, source.object_format)
            self._sources[source.project_id] = source
        return source

    def resolve_source(self, project_id: str, source_id: str, source_revision: int) -> RegisteredGitSource:
        source = self._sources.get(project_id)
        if source is None or (source.source_id, source.source_revision) != (source_id, source_revision):
            raise WorkspaceFileError("git_source_not_current")
        return source

    @contextmanager
    def open_commit(self, source: RegisteredGitSource, base_commit: str):
        if type(source) is not RegisteredGitSource:
            raise WorkspaceFileError("git_source_invalid")
        registered = self.resolve_source(source.project_id, source.source_id, source.source_revision)
        if source != registered:
            raise WorkspaceFileError("git_source_binding_mismatch")
        _object_id(base_commit, source.object_format)
        with self._root.exclusive() as root:
            with directory_at(root, managed_repository_slot(source)) as directory:
                validate_bare_metadata(directory, source.object_format)
                deadline = time.monotonic() + _OPERATION_SECONDS
                tree = _inspect(directory, source, base_commit, deadline)
                allowed = {item.path: item for item in tree.files}
                active = [True]

                def read_file(entry: GitFile) -> bytes:
                    if not active[0] or allowed.get(entry.path) != entry:
                        raise WorkspaceFileError("git_file_scope_mismatch")
                    data = _read_object(directory, "blob", entry.blob_id, MAX_FILE_BYTES, deadline)
                    if len(data) != entry.size_bytes or content_digest(data) != entry.content_digest:
                        raise WorkspaceFileError("git_file_digest_mismatch")
                    return data

                try:
                    yield tree, read_file
                finally:
                    active[0] = False

    def inspect_commit(self, source: RegisteredGitSource, base_commit: str) -> SourceTree:
        with self.open_commit(source, base_commit) as (tree, _):
            return tree

    def close(self) -> None:
        self._root.close()
