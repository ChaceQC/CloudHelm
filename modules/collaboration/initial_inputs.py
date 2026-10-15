"""Exact registered initial inputs; these are not candidate or acceptance facts."""

from sqlalchemy.engine import Connection

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_declaration
from modules.collaboration.records import read_registered_reference, validate_declaration_references
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.task_facts import InputSetMetadata, RegisteredReference


def validate_initial_input_set(
    connection: Connection, task, input_set_ref: EngineeringRef,
) -> tuple[RegisteredReference, RegisteredReference]:
    """Resolve this Task's declaration and exact six-reference engineering input set."""
    declaration = read_declaration(connection, task)
    records = validate_declaration_references(connection, task["project_id"], declaration)
    record = read_registered_reference(connection, task["project_id"], input_set_ref)
    if not isinstance(record.metadata, InputSetMetadata):
        raise TaskBoundaryError("registered_input_set_required")
    expected = [value.reference for value in records.values()]
    expected.append(records["acceptance_assets_ref"].metadata.method_ref)
    actual = record.metadata.input_set.references
    # Compare entire references, including revisions, authority and metadata digests.
    expected_json = {value.model_dump_json() for value in expected}
    actual_json = {value.model_dump_json() for value in actual}
    if actual_json != expected_json:
        raise TaskBoundaryError("initial_input_declaration_mismatch")
    for reference in actual:
        read_registered_reference(connection, task["project_id"], reference)
    return record, records["source_ref"]
