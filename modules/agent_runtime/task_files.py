"""Read bounded current diffs through the same registered workspace file service."""

from importlib import import_module

from sqlalchemy import select

from database.uow import UnitOfWork
from modules.collaboration.errors import TaskBoundaryError
from modules.projects.source_tables import project_git_sources
from modules.workspaces.file_operations import WorkspaceFileService
from modules.workspaces.git_objects import GitObjectStore
from modules.workspaces.safe_paths import WorkspaceFileError
from packages.contracts.p1.workspace_git import RegisteredGitSource
from packages.contracts.p1.workspace_records import workspace_metadata_digest
from .source_context import safe_context_text, secret_context_path


def read_task_workspace_diff(engine, spec):
    with UnitOfWork(engine) as uow:
        row = uow.connection.execute(select(project_git_sources).where(
            project_git_sources.c.project_id == spec.binding.project_id,
            project_git_sources.c.source_id == spec.binding.source_id,
            project_git_sources.c.source_revision == spec.binding.source_revision)).mappings().one()
        source = RegisteredGitSource.model_validate(row["source_json"])
        if workspace_metadata_digest(source) != row["source_digest"]:
            raise TaskBoundaryError("git_source_record_invalid")
    registry_module = import_module("services.dev-runner.engineering_registry")
    try:
        registry = registry_module.EngineeringRegistry(registry_module.load_registration())
        with registry.admit(0) as storage:
            git = GitObjectStore(storage.git_root)
            service = None
            try:
                git.register_source(source)
                service = WorkspaceFileService(storage.workspace_root, git, lambda _: spec)
                status = service.status(spec.materialization_operation_id)
                changes = [change for change in status.changes if not secret_context_path(change.path)]
                files, total = [], 0
                for change in changes[:16]:
                    diff = service.diff(spec.materialization_operation_id, change.path,
                                        expected_manifest_digest=status.current_manifest_digest)
                    filtered = safe_context_text(diff.patch)
                    patch = ("[REDACTED]" if filtered != diff.patch else diff.patch).encode("utf-8")
                    limit = min(8192, 32768 - total)
                    text = patch[:limit].decode("utf-8", errors="ignore")
                    total += len(text.encode("utf-8"))
                    files.append({"path": change.path, "patch": text, "binary": diff.binary,
                        "truncated": diff.truncated or len(patch) > limit,
                        "reason_code": "output_limit" if len(patch) > limit else diff.reason_code})
                return {"workspace_id": spec.binding.workspace_id, "work_item_id": spec.binding.work_item_id, "files": files,
                        "truncated": status.changes_truncated or len(changes) > 16
                        or any(item["truncated"] for item in files)}
            finally:
                if service is not None:
                    service.close()
                git.close()
    except WorkspaceFileError as error:
        raise TaskBoundaryError(error.code) from None
    except (OSError, registry_module.EngineeringRegistryError):
        raise TaskBoundaryError("agent_workspace_reader_unavailable") from None
