"""Same-transaction pending facts from the owning engineering domains."""

from database.uow import require_transaction
from modules.collaboration.operation_projection import merge_operation_facts


def read_engineering_operation_blockers(connection, task_id):
    """Accepted/unknown physical work blocks completion and cancellation alike."""
    # Domain readers import Task mechanics; resolve them after module import.
    from modules.delivery.queries import pending_build_operations
    from modules.workspaces.operations import pending_workspace_operations

    require_transaction(connection)
    workspace = pending_workspace_operations(connection, task_id)
    builds = pending_build_operations(connection, task_id)
    return merge_operation_facts(workspace, builds)
