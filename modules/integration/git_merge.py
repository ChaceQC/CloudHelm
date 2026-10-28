"""Fixed Git integration attempts and atomic target-branch publication."""

import json
import time
from dataclasses import dataclass
from typing import Literal

import rfc8785

from modules.workspaces.git_objects import _object_id, _read_object, read_commit_files
from modules.workspaces.git_process import run_git
from modules.workspaces.reference_seed import _write_object
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p1.workspace_git import (
    RegisteredGitSource, WorkspaceManifest, content_digest, workspace_path,
)

_SECONDS = 60
_METADATA_LIMIT = 256 * 1024
_MERGE_OUTPUT_LIMIT = 4 * 1024 * 1024
_UNSUPPORTED_TREE = {
    "git_path_unsupported", "git_tree_invalid", "git_entry_type_unsupported", "git_extension_unsupported",
    "git_attributes_unsupported", "git_lfs_unsupported", "git_source_limit_exceeded",
    "git_tree_limit_exceeded", "git_source_paths_unsupported",
}


@dataclass(frozen=True)
class MergePreparation:
    state: Literal["prepared", "conflict", "pending"]
    base_commit: str
    candidate_commit: str
    integrated_commit: str | None = None
    conflict_paths: tuple[str, ...] = ()
    conflict_paths_truncated: bool = False
    reason_code: str | None = None
    applied: bool = False
    apply_state: Literal["not_started", "applied", "unknown"] = "not_started"


def _refs(operation_id: str) -> tuple[str, str, str, str]:
    if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 160:
        raise WorkspaceFileError("merge_operation_invalid")
    suffix = content_digest(rfc8785.dumps(operation_id))[7:]
    return tuple(f"refs/cloudhelm/merge-{kind}/{suffix}" for kind in ("intents", "results", "started", "applied"))


def _reference(directory: int, source: RegisteredGitSource, ref: str, deadline: float) -> str | None:
    code, raw = run_git(directory, ("rev-parse", "--verify", "--quiet", "--end-of-options", ref),
                        limit=80, deadline=deadline, accepted_codes=(0, 1))
    if code == 1:
        return None
    try:
        return _object_id(raw.decode("ascii").strip(), source.object_format)
    except UnicodeError:
        raise WorkspaceFileError("merge_reference_invalid") from None


def _target(directory: int, source: RegisteredGitSource, deadline: float) -> str:
    code, _ = run_git(directory, ("symbolic-ref", "--quiet", source.target_branch),
                      limit=256, deadline=deadline, accepted_codes=(0, 1))
    if code == 0:
        raise WorkspaceFileError("git_target_branch_symbolic")
    tip = _reference(directory, source, source.target_branch, deadline)
    if tip is None:
        raise WorkspaceFileError("git_target_branch_unavailable")
    _read_object(directory, "commit", tip, 1024 * 1024, deadline)
    return tip


def _commit_parts(directory: int, source: RegisteredGitSource, commit: str, deadline: float) -> tuple[str, tuple[str, ...]]:
    _object_id(commit, source.object_format)
    raw = _read_object(directory, "commit", commit, 1024 * 1024, deadline)
    try:
        headers = raw.split(b"\n\n", 1)[0].splitlines()
        if not headers or not headers[0].startswith(b"tree "):
            raise ValueError
        tree = _object_id(headers[0][5:].decode("ascii"), source.object_format)
        parents = tuple(_object_id(line[7:].decode("ascii"), source.object_format)
                        for line in headers[1:] if line.startswith(b"parent "))
        return tree, parents
    except (UnicodeError, ValueError):
        raise WorkspaceFileError("merge_commit_invalid") from None


def _metadata_bytes(tree: str, parents: tuple[str, ...], payload: dict) -> bytes:
    headers = f"tree {tree}\n" + "".join(f"parent {parent}\n" for parent in parents)
    return (headers + "author CloudHelm integration <integration@cloudhelm.invalid> 0 +0000\n"
            "committer CloudHelm integration <integration@cloudhelm.invalid> 0 +0000\n\n").encode("ascii") + rfc8785.dumps(payload) + b"\n"


def _checked_tree(directory: int, commit: str, deadline: float) -> str:
    tree, files = read_commit_files(directory, commit, "", deadline)
    try:
        WorkspaceManifest(files=files)
    except ValueError:
        raise WorkspaceFileError("git_source_paths_unsupported") from None
    return tree


def _metadata(directory: int, source: RegisteredGitSource, ref: str, deadline: float) -> tuple[str, dict] | None:
    oid = _reference(directory, source, ref, deadline)
    if oid is None:
        return None
    raw = _read_object(directory, "commit", oid, _METADATA_LIMIT, deadline)
    try:
        payload = json.loads(raw.split(b"\n\n", 1)[1])
        if not isinstance(payload, dict):
            raise ValueError
    except (IndexError, UnicodeError, ValueError):
        raise WorkspaceFileError("merge_record_invalid") from None
    return oid, payload


def _publish(directory: int, source: RegisteredGitSource, ref: str, tree: str,
             parents: tuple[str, ...], payload: dict, deadline: float) -> str:
    oid = _write_object(directory, "commit", _metadata_bytes(tree, parents, payload), source.object_format)
    run_git(directory, ("update-ref", "--no-deref", ref, oid, "0" * len(oid)),
            limit=128, deadline=deadline)
    return oid


def _query(directory: int, source: RegisteredGitSource, operation_id: str, deadline: float) -> MergePreparation | None:
    intent_ref, result_ref, started_ref, applied_ref = _refs(operation_id)
    intent = _metadata(directory, source, intent_ref, deadline)
    if intent is None:
        return None
    intent_oid, body = intent
    try:
        if (set(body) != {"schema", "operation_id", "source", "base_commit", "candidate_commit"}
                or body["schema"] != "cloudhelm-git-merge-intent-r1"
                or body["operation_id"] != operation_id or body["source"] != source.model_dump(mode="json")):
            raise ValueError
        base = _object_id(body["base_commit"], source.object_format)
        candidate = _object_id(body["candidate_commit"], source.object_format)
        tree, _ = _commit_parts(directory, source, base, deadline)
        if _read_object(directory, "commit", intent_oid, _METADATA_LIMIT, deadline) != _metadata_bytes(
                tree, (base, candidate), body):
            raise ValueError
        result = _metadata(directory, source, result_ref, deadline)
        started = _reference(directory, source, started_ref, deadline)
        applied = _reference(directory, source, applied_ref, deadline)
        if result is None:
            if started is not None or applied is not None:
                raise ValueError
            return MergePreparation("pending", base, candidate, reason_code="merge_preparation_unconfirmed")
        result_oid, saved = result
        if (set(saved) != {"schema", "intent", "state", "integrated_commit", "conflict_paths",
                           "conflict_paths_truncated", "reason_code"}
                or saved["schema"] != "cloudhelm-git-merge-result-r1" or saved["intent"] != intent_oid
                or saved["state"] not in {"prepared", "conflict"}
                or not isinstance(saved["conflict_paths"], list)
                or len(saved["conflict_paths"]) > 128
                or type(saved["conflict_paths_truncated"]) is not bool
                or saved["reason_code"] not in {None, "git_conflict", "git_candidate_base_not_target",
                                                "git_integrated_tree_unsupported"}):
            raise ValueError
        paths = tuple(workspace_path(path) for path in saved["conflict_paths"])
        integrated = saved["integrated_commit"]
        if saved["state"] == "prepared":
            _object_id(integrated, source.object_format)
            if paths or saved["conflict_paths_truncated"] or saved["reason_code"] is not None:
                raise ValueError
            parents = (intent_oid, integrated)
        else:
            if integrated is not None or saved["reason_code"] is None or started is not None or applied is not None:
                raise ValueError
            parents = (intent_oid,)
        if (_read_object(directory, "commit", result_oid, _METADATA_LIMIT, deadline)
                != _metadata_bytes(tree, parents, saved) or started not in {None, integrated}
                or applied not in {None, integrated} or applied is not None and started is None):
            raise ValueError
        apply_state = "not_started"
        if started is not None:
            apply_state = "unknown"
            try:
                tip = _target(directory, source, deadline)
                code, _ = run_git(directory, ("merge-base", "--is-ancestor", integrated, tip),
                                  limit=0, deadline=deadline, accepted_codes=(0, 1))
                if code == 0:
                    apply_state = "applied"
            except WorkspaceFileError:
                pass
        return MergePreparation(saved["state"], base, candidate, integrated, paths,
                                saved["conflict_paths_truncated"], saved["reason_code"],
                                apply_state == "applied", apply_state)
    except WorkspaceFileError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise WorkspaceFileError("merge_record_invalid") from None


def _conflicts(output: bytes) -> tuple[tuple[str, ...], bool]:
    fields = output.split(b"\0")
    paths = set()
    try:
        for item in fields[1:]:
            if not item:
                break
            _, path = item.split(b"\t", 1)
            paths.add(workspace_path(path.decode("utf-8")))
    except (ValueError, UnicodeError):
        raise WorkspaceFileError("merge_output_invalid") from None
    ordered = sorted(paths, key=lambda path: path.encode("utf-8"))
    return tuple(ordered[:128]), len(ordered) > 128


class MergeGitStore:
    """Trusted caller owns admission and validation; this store owns Git facts only."""

    def __init__(self, git):
        self._git = git

    def current_tip(self, source: RegisteredGitSource) -> str:
        with self._git.integration_repository(source) as directory:
            return _target(directory, source, time.monotonic() + _SECONDS)

    def query(self, source: RegisteredGitSource, operation_id: str) -> MergePreparation | None:
        with self._git.integration_repository(source) as directory:
            return _query(directory, source, operation_id, time.monotonic() + _SECONDS)

    def prepare(self, source: RegisteredGitSource, operation_id: str, candidate_commit: str) -> MergePreparation:
        if source.source_prefix:
            raise WorkspaceFileError("merge_source_prefix_unsupported")
        if source.access_mode != "read_write":
            raise WorkspaceFileError("merge_source_read_only")
        _object_id(candidate_commit, source.object_format)
        with self._git.integration_repository(source) as directory:
            deadline = time.monotonic() + _SECONDS
            existing = _query(directory, source, operation_id, deadline)
            if existing is not None:
                if existing.candidate_commit != candidate_commit:
                    raise WorkspaceFileError("merge_request_digest_conflict")
                return existing
            _, candidate_parents = _commit_parts(directory, source, candidate_commit, deadline)
            if len(candidate_parents) != 1:
                raise WorkspaceFileError("merge_candidate_parent_invalid")
            _checked_tree(directory, candidate_commit, deadline)
            _checked_tree(directory, candidate_parents[0], deadline)
            base = _target(directory, source, deadline)
            tree = _checked_tree(directory, base, deadline)
            intent_ref, result_ref, _, _ = _refs(operation_id)
            body = {"schema": "cloudhelm-git-merge-intent-r1", "operation_id": operation_id,
                    "source": source.model_dump(mode="json"), "base_commit": base,
                    "candidate_commit": candidate_commit}
            intent = _publish(directory, source, intent_ref, tree, (base, candidate_commit), body, deadline)
            code, _ = run_git(directory, ("merge-base", "--is-ancestor", candidate_parents[0], base),
                              limit=0, deadline=deadline, accepted_codes=(0, 1))
            state, integrated, paths, truncated, reason = "conflict", None, (), False, "git_candidate_base_not_target"
            if code == 0:
                code, output = run_git(directory, ("merge-tree", "--write-tree", "-z", base, candidate_commit),
                                       limit=_MERGE_OUTPUT_LIMIT, deadline=deadline, accepted_codes=(0, 1))
                if code == 1:
                    paths, truncated = _conflicts(output)
                    reason = "git_conflict"
                else:
                    try:
                        merged_tree = _object_id(output.split(b"\0", 1)[0].strip().decode("ascii"), source.object_format)
                    except UnicodeError:
                        raise WorkspaceFileError("merge_output_invalid") from None
                    content = (f"tree {merged_tree}\nparent {base}\nparent {candidate_commit}\n"
                               "author CloudHelm integration <integration@cloudhelm.invalid> 0 +0000\n"
                               "committer CloudHelm integration <integration@cloudhelm.invalid> 0 +0000\n\n"
                               f"CloudHelm integration r1\noperation {content_digest(rfc8785.dumps(operation_id))}\n").encode("ascii")
                    integrated = _write_object(directory, "commit", content, source.object_format)
                    try:
                        _checked_tree(directory, integrated, deadline)
                        state, reason = "prepared", None
                    except WorkspaceFileError as error:
                        if error.code not in _UNSUPPORTED_TREE:
                            raise
                        integrated, reason = None, "git_integrated_tree_unsupported"
            result = {"schema": "cloudhelm-git-merge-result-r1", "intent": intent, "state": state,
                      "integrated_commit": integrated, "conflict_paths": list(paths),
                      "conflict_paths_truncated": truncated, "reason_code": reason}
            parents = (intent, integrated) if integrated is not None else (intent,)
            _publish(directory, source, result_ref, tree, parents, result, deadline)
            return MergePreparation(state, base, candidate_commit, integrated, paths, truncated, reason)

    def apply(self, source: RegisteredGitSource, operation_id: str, expected_base_commit: str,
              integrated_commit: str) -> Literal["merged", "baseline_changed", "unknown"]:
        if source.source_prefix:
            raise WorkspaceFileError("merge_source_prefix_unsupported")
        if source.access_mode != "read_write":
            raise WorkspaceFileError("merge_source_read_only")
        _object_id(expected_base_commit, source.object_format)
        _object_id(integrated_commit, source.object_format)
        with self._git.integration_repository(source) as directory:
            deadline = time.monotonic() + _SECONDS
            prepared = _query(directory, source, operation_id, deadline)
            if prepared is None or prepared.state != "prepared":
                raise WorkspaceFileError("merge_preparation_not_ready")
            if (prepared.base_commit, prepared.integrated_commit) != (expected_base_commit, integrated_commit):
                raise WorkspaceFileError("merge_request_digest_conflict")
            if prepared.applied:
                return "merged"
            if prepared.apply_state == "unknown":
                return "unknown"
            if _target(directory, source, deadline) != expected_base_commit:
                return "baseline_changed"
            started_ref, applied_ref = _refs(operation_id)[2:]
            try:
                run_git(directory, ("update-ref", "--no-deref", started_ref, integrated_commit,
                                    "0" * len(integrated_commit)), limit=128, deadline=deadline)
            except WorkspaceFileError:
                return "unknown"
            transaction = (f"start\noption no-deref\nupdate {source.target_branch} {integrated_commit} {expected_base_commit}\n"
                           f"create {applied_ref} {integrated_commit}\nprepare\ncommit\n").encode("utf-8")
            try:
                code, _ = run_git(directory, ("update-ref", "--stdin"), input_data=transaction, limit=128,
                                  deadline=deadline, accepted_codes=(0, 1, 128))
            except WorkspaceFileError as error:
                if error.code == "git_stop_unconfirmed":
                    return "unknown"
                try:
                    result = _query(directory, source, operation_id, time.monotonic() + _SECONDS)
                except WorkspaceFileError:
                    return "unknown"
                return "merged" if result is not None and result.applied else "unknown"
            if code == 0:
                return "merged"
            result = _query(directory, source, operation_id, deadline)
            if result is not None and result.applied:
                return "merged"
            if _target(directory, source, deadline) != expected_base_commit:
                return "baseline_changed"
            return "unknown"
