"""Locked persistence and current-input checks for human-test sessions."""

from datetime import UTC

from sqlalchemy import func, insert, select, update

from modules.agent_runtime.tables import agent_runs, agent_sessions
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.guards import MAX_REVISION
from modules.collaboration.records import reference_key
from modules.integration.candidates import _current_input
from modules.integration.human_test_tables import human_test_sessions
from modules.integration.validity import selected_verification
from modules.sync.events import append_event
from packages.contracts.p2.human_tests import HUMAN_TEST_SCHEMA, HumanTestSession


def now_utc(connection):
    return connection.scalar(select(func.clock_timestamp())).astimezone(UTC)


def read_session(connection, session_id, *, for_update=False):
    query = select(human_test_sessions.c.record_json).where(human_test_sessions.c.session_id == session_id)
    payload = connection.scalar(query.with_for_update() if for_update else query)
    if payload is None:
        raise TaskBoundaryError("human_test_not_found", status_code=404)
    return HumanTestSession.model_validate(payload)


def insert_session(connection, session):
    connection.execute(insert(human_test_sessions).values(
        session_id=session.session_id, project_id=session.project_id, task_id=session.task_id,
        round_id=session.round_id, revision=session.revision, state=session.state,
        record_json=session.model_dump(mode="json"), created_at=session.created_at,
    ))


def save_session(connection, session, **changes):
    if session.revision == MAX_REVISION:
        raise TaskBoundaryError("revision_exhausted")
    changed = HumanTestSession.model_validate(session.model_copy(
        update={**changes, "revision": session.revision + 1}).model_dump())
    updated = connection.execute(update(human_test_sessions).where(
        human_test_sessions.c.session_id == session.session_id,
        human_test_sessions.c.revision == session.revision,
    ).values(revision=changed.revision, state=changed.state,
             record_json=changed.model_dump(mode="json")))
    if updated.rowcount != 1:
        raise TaskBoundaryError("human_test_revision_conflict")
    return changed


def record_session(connection, session, event_type, command_id=None):
    append_event(connection, command_id=command_id or session.command_id, project_id=session.project_id,
        aggregate_kind="human_test_session", aggregate_id=session.session_id,
        aggregate_version=session.revision, event_type=event_type, schema_version=HUMAN_TEST_SCHEMA,
        payload=session)


def current_verification(connection, task, session):
    view = selected_verification(connection, task)
    if (view is None or not view.usable or view.report.report_id != session.verification_report_id
            or view.report.candidate_id != session.candidate_id
            or view.report.evidence.input_set_ref != session.final_input_set_ref
            or view.report.evidence.subject_ref != session.candidate_ref
            or task["input_status"] != "valid" or task["cancel_requested_at"] is not None
            or task["input_validity_revision"] != session.input_validity_revision
            or _current_input(connection, task) != reference_key(task["project_id"], session.source_input_set_ref)):
        raise TaskBoundaryError("human_test_candidate_not_current")
    if task["state"] != "completed" and task["control_revision"] != session.control_revision:
        raise TaskBoundaryError("human_test_candidate_not_current")
    return view


def require_no_active_run(connection, task_id):
    active = connection.scalar(select(agent_runs.c.run_id).join(
        agent_sessions, agent_sessions.c.session_id == agent_runs.c.session_id,
    ).where(agent_sessions.c.task_id == task_id, agent_runs.c.state.in_(("queued", "running"))).limit(1))
    if active is not None:
        raise TaskBoundaryError("human_test_active_run")
