"""Same-transaction pending facts from the owning engineering domains."""

from database.uow import require_transaction
from modules.collaboration.errors import TaskBoundaryError


def read_engineering_operation_blockers(connection, task_id):
    """Accepted/unknown physical work blocks completion and cancellation alike."""
    # Domain readers import Task mechanics; resolve them after module import.
    from modules.delivery.queries import pending_build_operations
    from modules.workspaces.operations import pending_workspace_operations

    require_transaction(connection)
    values = (*pending_workspace_operations(connection, task_id), *pending_build_operations(connection, task_id))
    if len(values) > 128 or len({item.operation_ref.object_id for item in values}) != len(values):
        raise TaskBoundaryError("engineering_operation_scope_too_large")
    return values
