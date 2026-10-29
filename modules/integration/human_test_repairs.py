"""Human feedback after completion creates a linked draft at the tested source."""

from sqlalchemy import select

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_declaration
from modules.collaboration.lifecycle_commands import _insert_task
from modules.collaboration.records import _store_reference, read_registered_reference, reference_key
from modules.collaboration.tables import task_reference_records
from modules.projects.tables import projects
from modules.sync.events import append_event
from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p1.task_requests import CreateTaskRequest, TaskBudget
from packages.contracts.p1.task_facts import RegisteredReference, SourceMetadata


class HumanTestRepairLink(Contract):
    session_id: Identifier
    original_task_id: Identifier
    repair_task_id: Identifier
    candidate_id: Identifier


def create_human_test_repair(uow, context, session, feedback):
    """The authorized conclusion command owns this transaction and deduplication."""
    source_ref = next((ref for ref in session.input_set.references
                       if ref.kind == "source" and ref.object_id == "candidate-source-" + session.candidate_id), None)
    if source_ref is None:
        raise TaskBoundaryError("human_test_repair_source_unavailable")
    import rfc8785

    from modules.integration.validity import selected_verification

    selected = selected_verification(uow.connection, context.task)
    proof = read_registered_reference(uow.connection, session.project_id, selected.evidence_ref)
    metadata = SourceMetadata(commit=source_ref.revision)
    key = reference_key(session.project_id, source_ref)
    existing = uow.connection.scalar(select(task_reference_records.c.reference_key).where(
        task_reference_records.c.reference_key == key))
    if existing is None:
        identity = "human-repair-source-" + key[7:]
        record = RegisteredReference(project_id=session.project_id, registration_id=identity,
            source_id=proof.source_id, source_record_id=identity, reference=source_ref,
            metadata=metadata, observed_at_utc=session.conclusion.concluded_at_utc)
        _store_reference(uow.connection, record, rfc8785.dumps(metadata.model_dump(mode="json")),
                         context.authorization.envelope)
    elif read_registered_reference(uow.connection, session.project_id, source_ref).metadata != metadata:
        raise TaskBoundaryError("human_test_repair_source_changed")
    declaration = read_declaration(uow.connection, context.task)
    declaration = declaration.model_copy(update={
        "title": ("人测修复：" + declaration.title)[:160],
        "goal": ("修复人测反馈（" + session.session_id + "）：\n" + feedback.summary)[:4096],
        "source_ref": source_ref,
        "budget": TaskBudget(amount="0", currency=declaration.budget.currency),
    })
    project = uow.connection.execute(select(projects).where(
        projects.c.project_id == session.project_id,
    ).with_for_update()).mappings().one()
    request = CreateTaskRequest(expected_project_revision=project["revision"], declaration=declaration)
    result = _insert_task(uow, context.envelope, project, request)
    link = HumanTestRepairLink(session_id=session.session_id, original_task_id=session.task_id,
                              repair_task_id=result.task_id, candidate_id=session.candidate_id)
    append_event(uow.connection, command_id=context.envelope.command_id, project_id=session.project_id,
                 aggregate_kind="human_test", aggregate_id=session.session_id,
                 aggregate_version=session.revision + 1, event_type="human_test.repair_created",
                 schema_version="p2-human-test-r1", payload=link)
    return result.task_id
