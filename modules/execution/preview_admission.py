"""An explicitly selected human test remains independent after Task completion."""

from datetime import datetime

from sqlalchemy import select

from database.commands import get_by_id
from modules.collaboration.guards import check_task_revisions, require_ordinary_progress
from modules.execution.registry import read_runner
from packages.contracts.p1.resource_protocol import DEVELOPMENT_BACKEND, canonical_digest


def require_resource_progress(uow, actor, task, request, *, at_start=False):
    versions = dict(expected_version=task["version"] if at_start else request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision)
    if task["state"] != "completed":
        return require_ordinary_progress(uow.connection, task["task_id"], **versions, allowed_states=("draft", "active"))
    check_task_revisions(task, **versions)
    if actor.principal.kind != "human" or request.backend != DEVELOPMENT_BACKEND or request.resources.hard_limits.preview_slots != 1:
        raise ValueError("resource_completed_task_closed")
    from modules.integration.human_test_records import current_verification
    from modules.integration.human_test_tables import human_test_sessions
    from modules.workspaces.preview_access_tables import preview_environments
    from modules.workspaces.preview_environment_tables import preview_environment_intents
    from packages.contracts.p2.human_tests import HumanTestSession
    from packages.contracts.p2.previews import PreviewEnvironmentRecord

    rows = uow.connection.execute(select(human_test_sessions.c.record_json).where(
        human_test_sessions.c.task_id == task["task_id"], human_test_sessions.c.state == "preparing")).scalars().all()
    for value in rows:
        session = HumanTestSession.model_validate(value)
        origin = get_by_id(uow.connection, session.command_id)
        if origin.envelope.caller != actor.principal:
            continue
        environment = uow.connection.scalar(select(preview_environments.c.record_json).where(
            preview_environments.c.record_json["human_test_session_id"].astext == session.session_id))
        if environment is None:
            continue
        environment = PreviewEnvironmentRecord.model_validate(environment)
        runner = read_runner(uow, request.resources.identity.executor_instance_id)
        expected = "engineering-resource-" + canonical_digest(
            {"key": environment.environment_id, "storage": runner.storage.model_dump(mode="json")})[7:47]
        intent = uow.connection.scalar(select(preview_environment_intents.c.request_json).where(
            preview_environment_intents.c.operation_id == environment.environment_id))
        if (environment.state == "preparing" and request.resources.identity.reservation_id == expected
                and request.resources.identity.operation_id == expected and intent is not None
                and intent.get("resource_deadline") is not None
                and request.expires_at_utc == datetime.fromisoformat(intent["resource_deadline"])):
            current_verification(uow.connection, task, session)
            return task
    raise ValueError("resource_completed_human_preview_required")
