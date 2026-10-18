"""Current Workspace source identity from the controlled, mutable file view."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from modules.workspaces.safe_paths import PrivateRoot, WorkspaceFileError, directory_at
from modules.workspaces.workspace_views import observe

from .workspace_development_inputs import workspace_storage_id
from .toolchain import ProbeFailure


@dataclass(frozen=True)
class WorkspaceSourceObservation:
    manifest_digest: str
    source_path: str
    file_count: int
    total_bytes: int


def observe_workspace_source(storage, binding) -> WorkspaceSourceObservation:
    """Observe actual live bytes under the same short workspace lock as writes."""
    root = None
    files = -1
    try:
        storage.observe()
        root = PrivateRoot(storage.workspace_root)
        workspace_id = workspace_storage_id(binding)
        with root.exclusive() as root_fd, directory_at(root_fd, workspace_id) as workspace_fd:
            with directory_at(workspace_fd, "files") as files_fd:
                files = os.dup(files_fd)
                expected = str(Path(storage.workspace_root) / workspace_id / "files")
                source = os.readlink(f"/proc/self/fd/{files}")
                if source != expected:
                    raise ProbeFailure("workspace_development_source_path_mismatch")
                current = observe(files)
        storage.observe()
        return WorkspaceSourceObservation(
            manifest_digest=current.digest, source_path=source,
            file_count=len(current.manifest.files),
            total_bytes=sum(item.size_bytes for item in current.manifest.files),
        )
    except ProbeFailure:
        raise
    except (WorkspaceFileError, OSError, ValueError, AttributeError):
        raise ProbeFailure("workspace_development_source_observation_failed") from None
    finally:
        if files >= 0:
            os.close(files)
        if root is not None:
            root.close()
