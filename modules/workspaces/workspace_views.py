"""Bounded current-file observations and in-process text diffs, never candidates."""

import difflib
import os
import stat
from contextlib import contextmanager
from dataclasses import dataclass

from modules.workspaces.safe_paths import WorkspaceFileError, _trusted, directory_at, read_regular
from packages.contracts.p1.workspace_git import (
    MAX_FILE_BYTES, MAX_FILES, MAX_SOURCE_BYTES, WorkspaceChange, WorkspaceDiff, WorkspaceFile,
    WorkspaceManifest, WorkspaceStatus, content_digest, manifest_bytes, workspace_path,
)

Fingerprint = tuple[int, int, int, int, int, int]


def fingerprint(info) -> Fingerprint:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _safe_info(info, device: int) -> None:
    _trusted(info, directory=stat.S_ISDIR(info.st_mode), device=device)
    if info.st_mode & 0o7000:
        raise WorkspaceFileError("workspace_special_mode_unsupported")


@contextmanager
def file_parent(files: int, path: str):
    try:
        parts = workspace_path(path).split("/")
    except ValueError:
        raise WorkspaceFileError("workspace_path_invalid") from None
    if len(parts) > 1:
        with directory_at(files, "/".join(parts[:-1])) as parent:
            yield parent, parts[-1]
    else:
        yield files, parts[0]


def _read_entry(parent: int, name: str, path: str):
    try:
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        _safe_info(before, os.fstat(parent).st_dev)
        data = read_regular(parent, name, MAX_FILE_BYTES)
        after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if fingerprint(before) != fingerprint(after):
            raise WorkspaceFileError("workspace_file_changed")
        entry = WorkspaceFile(path=path, mode="100755" if before.st_mode & 0o111 else "100644",
                              size_bytes=len(data), content_digest=content_digest(data))
        return entry, fingerprint(after)
    except OSError:
        raise WorkspaceFileError("workspace_file_unavailable") from None


def file_state(files: int, path: str):
    with file_parent(files, path) as (parent, name):
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return None, None
        return _read_entry(parent, name, path)


@dataclass(frozen=True)
class FileObservation:
    manifest: WorkspaceManifest
    fingerprints: dict[str, Fingerprint]

    @property
    def digest(self) -> str:
        return content_digest(manifest_bytes(self.manifest.files))


def observe(files: int) -> FileObservation:
    entries, proofs, visited, total, directories = [], {}, [0], [0], {}
    device = os.fstat(files).st_dev

    def visit(parent: int, prefix: str, depth: int):
        before = os.fstat(parent)
        _safe_info(before, device)
        for name in sorted(os.listdir(parent)):
            visited[0] += 1
            if visited[0] > MAX_FILES * 2 or depth >= 32:
                raise WorkspaceFileError("workspace_tree_limit_exceeded")
            path = f"{prefix}/{name}" if prefix else name
            try:
                workspace_path(path)
            except ValueError:
                raise WorkspaceFileError("workspace_path_invalid") from None
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            _safe_info(info, device)
            if stat.S_ISDIR(info.st_mode):
                if path.casefold() in directories and directories[path.casefold()] != path:
                    raise WorkspaceFileError("workspace_path_conflict")
                directories[path.casefold()] = path
                with directory_at(parent, name) as child:
                    visit(child, path, depth + 1)
            else:
                entry, proof = _read_entry(parent, name, path)
                entries.append(entry)
                proofs[path] = proof
                total[0] += entry.size_bytes
                if len(entries) > MAX_FILES or total[0] > MAX_SOURCE_BYTES:
                    raise WorkspaceFileError("workspace_source_limit_exceeded")
        after = os.fstat(parent)
        if (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns):
            raise WorkspaceFileError("workspace_tree_changed")

    try:
        visit(files, "", 0)
        manifest = WorkspaceManifest(files=tuple(sorted(entries, key=lambda item: item.path.encode("utf-8"))))
        return FileObservation(manifest, proofs)
    except WorkspaceFileError:
        raise
    except (OSError, ValueError):
        raise WorkspaceFileError("workspace_tree_invalid") from None


def project_change(observation: FileObservation, path: str, replacement: WorkspaceFile | None) -> WorkspaceManifest:
    entries = [entry for entry in observation.manifest.files if entry.path != path]
    if replacement is not None:
        entries.append(replacement)
    try:
        return WorkspaceManifest(files=tuple(entries))
    except ValueError:
        raise WorkspaceFileError("workspace_source_limit_or_path_conflict") from None


def status_result(spec, initial, base: WorkspaceManifest, current: FileObservation, paths, unresolved: int):
    old, new = {item.path: item for item in base.files}, {item.path: item for item in current.manifest.files}
    selected = set(paths) if paths else set(old) | set(new)
    changes = []
    for path in sorted(selected, key=lambda value: value.encode("utf-8")):
        before, after = old.get(path), new.get(path)
        if before != after:
            kind = "added" if before is None else "deleted" if after is None else "modified"
            changes.append(WorkspaceChange(path=path, kind=kind, before=before, after=after))
    entries = [item for item in current.manifest.files if item.path in selected]
    return WorkspaceStatus(
        binding=spec.binding, materialization_operation_id=spec.materialization_operation_id,
        initial_manifest_digest=initial.manifest_digest, current_manifest_digest=current.digest,
        file_count=len(current.manifest.files), total_bytes=sum(item.size_bytes for item in current.manifest.files),
        files=tuple(entries[:128]), changes=tuple(changes[:128]), files_truncated=len(entries) > 128,
        changes_truncated=len(changes) > 128, change_count=len(changes), unresolved_operations=unresolved,
    )


def diff_result(binding, path, before, after, old: bytes | None, new: bytes | None) -> WorkspaceDiff:
    values = dict(binding=binding, path=path, before=before, after=after, patch="", binary=False, truncated=False)
    if old is None or new is None or len(old) > 65536 or len(new) > 65536:
        return WorkspaceDiff(**{**values, "truncated": True, "reason_code": "input_limit"})
    try:
        if b"\0" in old or b"\0" in new:
            raise UnicodeError
        old_lines, new_lines = old.decode("utf-8").splitlines(keepends=True), new.decode("utf-8").splitlines(keepends=True)
    except UnicodeError:
        return WorkspaceDiff(**{**values, "binary": True, "reason_code": "binary"})
    if len(old_lines) > 1024 or len(new_lines) > 1024:
        return WorkspaceDiff(**{**values, "truncated": True, "reason_code": "input_limit"})
    patch = bytearray()
    for line in difflib.unified_diff(old_lines, new_lines, fromfile="a/" + path, tofile="b/" + path):
        block = line.encode("utf-8")
        if len(patch) + len(block) > 65536:
            values.update(truncated=True, reason_code="output_limit")
            patch.extend(block[:65536 - len(patch)])
            break
        patch.extend(block)
    return WorkspaceDiff(**{**values, "patch": patch.decode("utf-8", errors="ignore")})
