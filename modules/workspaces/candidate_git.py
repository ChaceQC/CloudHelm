"""Immutable candidate Git objects and service-private refs, never a branch merge."""

import time

import rfc8785

from modules.workspaces.git_objects import _check_content, _read_object, read_commit_files
from modules.workspaces.reference_seed import _write_object, _write_tree
from modules.workspaces.safe_paths import WorkspaceFileError, directory_at, exists_at, read_regular, write_new_file
from packages.contracts.p1.workspace_candidates import candidate_freeze_digest
from packages.contracts.p1.workspace_git import GitFile, content_digest, manifest_bytes


def candidate_ref(operation_id):
    return "refs/cloudhelm/candidates/" + content_digest(rfc8785.dumps(operation_id))[7:]


def commit_bytes(tree_id, spec, operation_id):
    operation = content_digest(rfc8785.dumps(operation_id))
    return (
        f"tree {tree_id}\nparent {spec.binding.base_commit}\n"
        "author CloudHelm candidate <candidate@cloudhelm.invalid> 0 +0000\n"
        "committer CloudHelm candidate <candidate@cloudhelm.invalid> 0 +0000\n\n"
        f"Physical workspace candidate r1\noperation {operation}\nrequest {candidate_freeze_digest(spec)}\n"
    ).encode("ascii")


def prepare(directory, source, files, manifest, spec, operation_id):
    entries = []
    for entry in manifest.files:
        data = read_regular(files, entry.path, entry.size_bytes)
        if len(data) != entry.size_bytes or content_digest(data) != entry.content_digest:
            raise WorkspaceFileError("candidate_content_changed")
        _check_content(entry.path, data)
        if entry.path.split("/")[-1].casefold() in {".gitmodules", ".lfsconfig"}:
            raise WorkspaceFileError("git_extension_unsupported")
        oid = _write_object(directory, "blob", data, source.object_format)
        entries.append(GitFile(**entry.model_dump(), blob_id=oid))
    tree_id = _write_tree(directory, entries, source.object_format)
    commit = _write_object(directory, "commit", commit_bytes(tree_id, spec, operation_id), source.object_format)
    return commit


def retain(directory, operation_id, commit):
    ref = candidate_ref(operation_id)
    parent, name = ref.rsplit("/", 1)
    with directory_at(directory, parent, create=True) as refs:
        if exists_at(refs, name):
            if read_regular(refs, name, 80) != (commit + "\n").encode("ascii"):
                raise WorkspaceFileError("candidate_request_digest_conflict")
        else:
            write_new_file(refs, name, (commit + "\n").encode("ascii"))


def verify(directory, source, manifest, spec, operation_id, commit, *, require_ref=True):
    deadline = time.monotonic() + 60
    tree_id, entries = read_commit_files(directory, commit, "", deadline)
    if (content_digest(manifest_bytes(entries)) != spec.expected_manifest_digest
            or manifest_bytes(entries) != manifest_bytes(manifest.files)
            or _read_object(directory, "commit", commit, 65536, deadline) != commit_bytes(tree_id, spec, operation_id)):
        raise WorkspaceFileError("candidate_git_mismatch")
    if require_ref and read_regular(directory, candidate_ref(operation_id), 80) != (commit + "\n").encode("ascii"):
        raise WorkspaceFileError("candidate_git_mismatch")
