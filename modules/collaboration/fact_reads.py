"""Bounded same-transaction reads used when projecting Task completion facts."""

from sqlalchemy.engine import Connection

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.records import read_registered_reference, reference_key
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.task_facts import RegisteredReference
from packages.contracts.p1.task_results import TaskBlocker


def bounded_rows(connection: Connection, statement, code: str):
    rows = connection.execute(statement.limit(129)).mappings().all()
    if len(rows) > 128:
        raise TaskBoundaryError(code)
    return rows


class FactReader:
    """Cache only immutable reference data within this one caller-owned transaction."""

    def __init__(self, connection: Connection, project_id: str, task_id: str) -> None:
        self.connection = connection
        self.project_id = project_id
        self.task_id = task_id
        self.blockers: list[TaskBlocker] = []
        self._records: dict[str, RegisteredReference | None] = {}

    def block(self, code: str, object_id: str | None = None, object_kind: str = "task") -> None:
        value = TaskBlocker(code=code, object_kind=object_kind, object_id=object_id or self.task_id)
        if value not in self.blockers:
            self.blockers.append(value)
        if len(self.blockers) > 128:
            raise TaskBoundaryError("task_fact_projection_scope_too_large")

    def read(
        self, reference: EngineeringRef | str | None, kind: str | None = None,
        *, missing_code: str = "reference_not_registered",
    ) -> RegisteredReference | None:
        if reference is None:
            self.block(missing_code)
            return None
        key = reference_key(self.project_id, reference) if isinstance(reference, EngineeringRef) else reference
        if key not in self._records:
            try:
                self._records[key] = read_registered_reference(self.connection, self.project_id, reference)
            except TaskBoundaryError as error:
                self.block(error.code, key, "reference")
                self._records[key] = None
        result = self._records[key]
        if result is not None and kind is not None and result.metadata.record_kind != kind:
            self.block("reference_kind_mismatch", result.reference.object_id, "reference")
            return None
        return result
