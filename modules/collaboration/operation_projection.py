"""Complete, uniquely keyed operation facts shared by Task control projections."""

from collections.abc import Sequence

from modules.collaboration.errors import TaskBoundaryError
from packages.contracts.p0.task_control_contracts import OperationClosureFact

MAX_OPERATION_FACTS = 128


def merge_operation_facts(
    *sources: Sequence[OperationClosureFact],
) -> tuple[OperationClosureFact, ...]:
    """Merge every source without truncation and enforce the Task projection boundary."""
    if sum(len(source) for source in sources) > MAX_OPERATION_FACTS:
        raise TaskBoundaryError("task_fact_projection_scope_too_large")

    merged = []
    seen_ids: set[str] = set()
    for source in sources:
        for operation in source:
            operation_id = operation.operation_ref.object_id
            if operation_id in seen_ids:
                raise TaskBoundaryError("task_fact_projection_duplicate_operation")
            seen_ids.add(operation_id)
            merged.append(operation)
    return tuple(merged)
