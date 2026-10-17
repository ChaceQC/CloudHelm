"""Internal bounded content staging; commands persist only the content identity."""

from modules.workspaces.safe_paths import (
    PrivateRoot, WorkspaceFileError, directory_at, exists_at, read_regular, write_new_file,
)
from packages.contracts.p1.workspace_git import MAX_FILE_BYTES, content_digest


def stage_mutation_content(registry, content: bytes) -> str:
    """The ingress authorizes workspace.write before calling this storage adapter."""
    if type(content) is not bytes or len(content) > MAX_FILE_BYTES:
        raise WorkspaceFileError("workspace_mutation_content_invalid")
    digest = content_digest(content)
    with registry.admit(len(content)) as storage:
        root = PrivateRoot(storage.workspace_root)
        try:
            with root.exclusive() as directory, directory_at(directory, "mutation-payloads", create=True) as payloads:
                name = digest[7:]
                if not exists_at(payloads, name):
                    write_new_file(payloads, name, content)
                if read_regular(payloads, name, MAX_FILE_BYTES) != content:
                    raise WorkspaceFileError("workspace_mutation_content_mismatch")
        finally:
            root.close()
    return digest


def load_mutation_content(storage, replacement) -> bytes:
    # The file service owns the workspace lock; global storage admission excludes
    # independent staging writers. Taking a second flock here would deadlock.
    root = PrivateRoot(storage.workspace_root)
    try:
        raw = read_regular(root.fd, "mutation-payloads/" + replacement.content_digest[7:], MAX_FILE_BYTES)
        if len(raw) != replacement.size_bytes or content_digest(raw) != replacement.content_digest:
            raise WorkspaceFileError("workspace_mutation_content_mismatch")
        return raw
    finally:
        root.close()
