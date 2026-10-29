"""Optional fixed-candidate human test commands and bounded maintenance."""

from uuid import uuid4

from sqlalchemy import DateTime, cast, insert, or_, select, update

from database.commands import lock_and_get, save_result
from database.uow import UnitOfWork
from modules.collaboration.command_support import TaskCommandContext, lock_task_access, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_declaration
from modules.collaboration.guards import check_task_revisions, require_ordinary_progress, task_resource
from modules.collaboration.records import read_fact_source, read_registered_reference, reference_key
from modules.collaboration.tables import task_wait_conditions
from modules.identity.actors import AuthoritativeResource
from modules.identity.authorization import authorize_current
from modules.identity.tables import users
from modules.integration.candidates import _operation_access, _read
from modules.integration.human_test_conclusions import archive_conclusion
from modules.integration.human_test_records import (
    current_verification, insert_session, now_utc, read_session, record_session, require_no_active_run, save_session,
)
from modules.integration.human_test_tables import human_test_sessions
from modules.integration.merge_validity import require_merged_report
from modules.integration.validity import selected_verification
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, Principal, request_digest
from packages.contracts.p1.task_facts import HumanPolicyMetadata
from packages.contracts.p2.human_tests import (
    HUMAN_TEST_IDLE_DURATION, HUMAN_TEST_IDLE_GRACE, HUMAN_TEST_INITIAL_DURATION, HUMAN_TEST_RENEWAL_DURATION,
    HUMAN_TEST_SCHEMA, HumanTestCommandResult, HumanTestSession,
)


def _command(uow, actor, resource, action, request, key, suffix):
    authorization = authorize_current(uow, actor, resource, action)
    intent = CommandIntent(request_schema_revision=HUMAN_TEST_SCHEMA + "-" + suffix,
        caller=actor.principal, scope=resource.scope, target=resource.target_scope, action=action,
        expected_resource_revision=request.expected_version)
    command = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex, idempotency_key=key,
                              request_digest=request_digest(intent, request))
    return authorization, command, lock_and_get(uow.connection, command)


def _save_command(uow, command, authorization, session, status=200):
    result = HumanTestCommandResult(command_id=command.command_id, session=session)
    save_result(uow.connection, command, result, status_code=status, authorization=authorization.envelope)
    return result


def _session_context(uow, actor, session_id, request, key, action, suffix):
    identity = read_session(uow.connection, session_id)
    task, _ = lock_task_access(uow, actor, identity.task_id, "resource.read")
    session = read_session(uow.connection, session_id, for_update=True)
    if session.project_id != task["project_id"] or session.task_id != task["task_id"]:
        raise TaskBoundaryError("human_test_not_found", status_code=404)
    if action != "task.command" and (actor.principal.kind != "human" or actor.principal != session.tester):
        raise TaskBoundaryError("human_test_assigned_tester_required", status_code=403)
    resource = AuthoritativeResource(task["project_id"], "human_test_session", session_id,
                                     revision=session.revision, task_id=task["task_id"])
    authorization, command, existing = _command(uow, actor, resource, action, request, key, suffix)
    if existing is not None:
        return task, session, authorization, command, HumanTestCommandResult.model_validate(existing.result)
    check_task_revisions(task, expected_version=request.expected_version,
        expected_control_revision=request.expected_control_revision,
        expected_input_validity_revision=request.expected_input_validity_revision)
    if session.revision != request.expected_session_revision:
        raise TaskBoundaryError("human_test_revision_conflict")
    return task, session, authorization, command, None


def _latest(connection, session):
    latest = connection.scalar(select(human_test_sessions.c.session_id).where(
        human_test_sessions.c.task_id == session.task_id).order_by(
        human_test_sessions.c.created_at.desc(), human_test_sessions.c.session_id.desc()).limit(1))
    if latest != session.session_id:
        raise TaskBoundaryError("human_test_old_round")


def _close_wait(connection, session):
    if session.wait_condition_id is not None:
        connection.execute(update(task_wait_conditions).where(
            task_wait_conditions.c.wait_condition_id == session.wait_condition_id,
            task_wait_conditions.c.state == "waiting").values(state="closed"))


def _live_access(readiness, uow, actor, session):
    if readiness is None or readiness(uow, actor, session) != (session.environment_id, session.environment_ref):
        raise TaskBoundaryError("human_test_access_not_current")


def _within_idle_grace(session, at):
    return session.idle_warning_at is None or at < session.idle_warning_at + HUMAN_TEST_IDLE_GRACE


class HumanTestApplication:
    def __init__(self, engine, control_engine, *, prepare, readiness, stop, can_renew, create_repair):
        self.engine, self.control_engine = engine, control_engine
        self.prepare, self.readiness, self.stop = prepare, readiness, stop
        self.can_renew, self.create_repair = can_renew, create_repair

    def start(self, actor, task_id, request, *, idempotency_key):
        if actor.principal.kind != "human":
            raise TaskBoundaryError("human_test_human_required", status_code=403)
        with UnitOfWork(self.engine) as uow:
            task, _ = lock_task_access(uow, actor, task_id, "task.command")
            authorization, command, existing = _command(uow, actor, task_resource(task), "task.command",
                                                         request, idempotency_key, "start")
            if existing is not None:
                return HumanTestCommandResult.model_validate(existing.result)
            if task["state"] == "completed":
                check_task_revisions(task, expected_version=request.expected_version,
                    expected_control_revision=request.expected_control_revision,
                    expected_input_validity_revision=request.expected_input_validity_revision)
            else:
                require_ordinary_progress(uow.connection, task_id, expected_version=request.expected_version,
                    expected_control_revision=request.expected_control_revision,
                    expected_input_validity_revision=request.expected_input_validity_revision)
            require_no_active_run(uow.connection, task_id)
            if uow.connection.scalar(select(human_test_sessions.c.session_id).where(
                human_test_sessions.c.task_id == task_id,
                human_test_sessions.c.state.in_(("preparing", "awaiting_human", "testing"))).limit(1)):
                raise TaskBoundaryError("human_test_already_active")
            view = selected_verification(uow.connection, task)
            if view is None or not view.usable or view.report.candidate_id != request.candidate_id:
                raise TaskBoundaryError("human_test_verification_required")
            require_merged_report(uow.connection, task, view)
            candidate = _read(uow.connection, task, request.candidate_id)
            _operation_access(uow, actor, task, candidate.build_operation_id)
            from modules.workspaces.preview_profiles import fixed_preview_inputs

            if (request.test_config_ref, request.dataset_ref) != fixed_preview_inputs(uow.connection, candidate):
                raise TaskBoundaryError("human_test_fixed_inputs_required")
            artifacts = tuple(ref for ref in candidate.input_set.references
                              if ref.kind == "artifact" and ref.authority == "artifacts")
            declaration = read_declaration(uow.connection, task)
            policy = read_registered_reference(uow.connection, task["project_id"], declaration.human_test_policy_ref)
            if (not isinstance(policy.metadata, HumanPolicyMetadata)
                    or read_fact_source(uow.connection, task["project_id"], policy.source_id).purpose != "product"):
                raise TaskBoundaryError("human_test_policy_invalid")
            if uow.connection.scalar(select(users.c.user_id).where(
                users.c.user_id == request.tester_id, users.c.status == "active")) is None:
                raise TaskBoundaryError("human_test_tester_unavailable")
            context = TaskCommandContext(uow, actor, task, authorization, command)
            if task["state"] != "completed":
                update_task(context)
            session_id = "human-test-" + command.command_id
            session = HumanTestSession(session_id=session_id, command_id=command.command_id,
                project_id=task["project_id"], task_id=task_id, round_id=session_id, revision=1,
                task_version=context.task["version"], control_revision=task["control_revision"],
                input_validity_revision=task["input_validity_revision"], candidate_id=candidate.candidate_id,
                candidate_ref=view.report.evidence.subject_ref, source_input_set_ref=candidate.source_input_set_ref,
                verification_report_id=view.report.report_id, final_input_set_ref=view.report.evidence.input_set_ref,
                input_set=view.report.input_set, artifact_refs=artifacts,
                requirement_ref=declaration.requirement_ref, acceptance_assets_ref=declaration.acceptance_assets_ref,
                policy_ref=declaration.human_test_policy_ref, policy=policy.metadata,
                test_config_ref=request.test_config_ref, dataset_ref=request.dataset_ref,
                tester=Principal(kind="human", subject_id=request.tester_id), state="preparing",
                entry_authorization_decision_id=authorization.envelope.decision_id, created_at=now_utc(uow.connection))
            insert_session(uow.connection, session)
            if self.prepare is None:
                raise TaskBoundaryError("human_test_prepare_unavailable")
            prepared = self.prepare(uow, context, session)
            if prepared is not None:
                session = save_session(uow.connection, session, environment_id=prepared.environment_id)
            record_session(uow.connection, session, "human_test.preparing")
            return _save_command(uow, command, authorization, session, 202)

    def list(self, actor, task_id):
        with UnitOfWork(self.control_engine) as uow:
            task, _ = lock_task_access(uow, actor, task_id, "resource.read")
            rows = uow.connection.scalars(select(human_test_sessions.c.record_json).where(
                human_test_sessions.c.task_id == task_id, human_test_sessions.c.project_id == task["project_id"]
            ).order_by(human_test_sessions.c.created_at.desc(), human_test_sessions.c.session_id.desc()).limit(128))
            return tuple(HumanTestSession.model_validate(row) for row in rows)

    def query(self, actor, session_id):
        with UnitOfWork(self.control_engine) as uow:
            session = read_session(uow.connection, session_id)
            task, _ = lock_task_access(uow, actor, session.task_id, "resource.read")
            if task["project_id"] != session.project_id:
                raise TaskBoundaryError("human_test_not_found", status_code=404)
            return session

    def mark_ready(self, actor, session_id, request, *, idempotency_key):
        with UnitOfWork(self.engine) as uow:
            task, session, auth, command, existing = _session_context(
                uow, actor, session_id, request, idempotency_key, "human_test.enter", "ready")
            if existing is not None:
                return existing
            _latest(uow.connection, session)
            current_verification(uow.connection, task, session)
            require_no_active_run(uow.connection, task["task_id"])
            if session.state != "preparing" or self.readiness is None:
                raise TaskBoundaryError("human_test_not_ready")
            environment_id, environment_ref = self.readiness(uow, actor, session)
            environment = read_registered_reference(uow.connection, task["project_id"], environment_ref)
            if environment.metadata.record_kind != "environment" or "human_test" not in environment.metadata.support_scope:
                raise TaskBoundaryError("human_test_environment_evidence_required")
            at = now_utc(uow.connection)
            wait_id = "human-wait-" + session.command_id
            uow.connection.execute(insert(task_wait_conditions).values(wait_condition_id=wait_id,
                task_id=task["task_id"], required_for_completion=False, state="waiting",
                input_set_key=reference_key(task["project_id"], session.source_input_set_ref)))
            session = save_session(uow.connection, session, state="awaiting_human", environment_id=environment_id,
                environment_ref=environment_ref, wait_condition_id=wait_id,
                access_authorization_decision_id=auth.envelope.decision_id, ready_at=at,
                expires_at=at + HUMAN_TEST_INITIAL_DURATION, last_human_activity_at=at, preparation_reason=None)
            record_session(uow.connection, session, "human_test.ready", command.command_id)
            return _save_command(uow, command, auth, session)

    def conclude(self, actor, session_id, request, *, idempotency_key):
        action = {"passed": "human_test.pass", "changes_requested": "human_test.request_changes",
                  "skipped": "human_test.skip"}[request.conclusion]
        with UnitOfWork(self.engine) as uow:
            task, session, auth, command, existing = _session_context(
                uow, actor, session_id, request, idempotency_key, action, "conclude")
            if existing is not None:
                return existing
            _latest(uow.connection, session)
            view = current_verification(uow.connection, task, session)
            at = now_utc(uow.connection)
            active = (session.state in {"awaiting_human", "testing"} and at < session.expires_at
                      and _within_idle_grace(session, at))
            skipped_later = (request.conclusion == "skipped" and session.state in {
                "preparing", "awaiting_human", "testing", "expired", "cancelled"})
            if not active and not skipped_later:
                raise TaskBoundaryError("human_test_not_active")
            if active and request.conclusion != "skipped":
                _live_access(self.readiness, uow, actor, session)
            if request.conclusion == "skipped" and not session.policy.skip_allowed:
                raise TaskBoundaryError("human_skip_not_allowed")
            if request.feedback is not None:
                from modules.agent_runtime.context import safe_context_value

                data = request.feedback.model_dump(mode="json")
                if safe_context_value(data) != data:
                    raise TaskBoundaryError("human_test_feedback_contains_secret", status_code=422)
                for ref in request.feedback.attachment_refs:
                    read_registered_reference(uow.connection, task["project_id"], ref)
            if self.stop is None:
                raise TaskBoundaryError("human_test_stop_unavailable")
            context = TaskCommandContext(uow, actor, task, auth, command)
            fact_session = session.model_copy(update={"feedback": request.feedback})
            conclusion, conclusion_ref = archive_conclusion(uow, task, fact_session, request, auth, view, at)
            session = save_session(uow.connection, session, state="completed", ended_at=at,
                feedback=request.feedback, conclusion=conclusion, conclusion_ref=conclusion_ref)
            if request.conclusion == "changes_requested":
                if task["state"] == "completed":
                    if self.create_repair is None:
                        raise TaskBoundaryError("human_test_repair_unavailable")
                    self.create_repair(uow, context, session, request.feedback)
                else:
                    from modules.collaboration.rework import receive_feedback_in_uow

                    receive_feedback_in_uow(context, human_session=session)
            elif task["state"] != "completed":
                update_task(context)
            self.stop(uow, session)
            record_session(uow.connection, session, "human_test.concluded", command.command_id)
            return _save_command(uow, command, auth, session)

    def control(self, actor, session_id, request, action, *, idempotency_key):
        if action not in {"activity", "renew", "give_up", "cancel"}:
            raise TaskBoundaryError("human_test_control_invalid", status_code=422)
        with UnitOfWork(self.engine) as uow:
            identity = read_session(uow.connection, session_id)
            identity_action = ("task.command" if action == "cancel" and actor.principal != identity.tester
                               else "human_test.enter")
            task, session, auth, command, existing = _session_context(
                uow, actor, session_id, request, idempotency_key, identity_action, action)
            if existing is not None:
                return existing
            _latest(uow.connection, session)
            at = now_utc(uow.connection)
            if action in {"activity", "renew"}:
                current_verification(uow.connection, task, session)
                if (session.state not in {"awaiting_human", "testing"} or at >= session.expires_at
                        or not _within_idle_grace(session, at)):
                    raise TaskBoundaryError("human_test_not_active")
                _live_access(self.readiness, uow, actor, session)
                changes = {"state": "testing", "last_human_activity_at": at, "idle_warning_at": None}
                if action == "renew":
                    if session.renewed_at is not None or self.can_renew is None or not self.can_renew(uow, session):
                        raise TaskBoundaryError("human_test_renewal_unavailable")
                    changes.update(renewed_at=at, expires_at=session.expires_at + HUMAN_TEST_RENEWAL_DURATION)
            else:
                if session.state not in {"preparing", "awaiting_human", "testing"} or self.stop is None:
                    raise TaskBoundaryError("human_test_stop_unavailable")
                changes = {"state": "cancelled", "ended_at": at}
                _close_wait(uow.connection, session)
            session = save_session(uow.connection, session, **changes)
            if action in {"give_up", "cancel"}:
                self.stop(uow, session)
            record_session(uow.connection, session, "human_test." + action, command.command_id)
            return _save_command(uow, command, auth, session)

    def maintenance(self):
        with UnitOfWork(self.engine) as uow:
            at = now_utc(uow.connection)
            record = human_test_sessions.c.record_json
            ids = uow.connection.scalars(select(human_test_sessions.c.session_id).where(
                human_test_sessions.c.state.in_(("awaiting_human", "testing")), or_(
                    cast(record["expires_at"].astext, DateTime(timezone=True)) <= at,
                    cast(record["idle_warning_at"].astext, DateTime(timezone=True)) <= at - HUMAN_TEST_IDLE_GRACE,
                    record["idle_warning_at"].astext.is_(None) &
                    (cast(record["last_human_activity_at"].astext, DateTime(timezone=True)) <= at - HUMAN_TEST_IDLE_DURATION),
                )).order_by(human_test_sessions.c.created_at, human_test_sessions.c.session_id).limit(16)).all()
            changed = []
            for session_id in ids:
                identity = read_session(uow.connection, session_id)
                from modules.collaboration.guards import read_task

                read_task(uow.connection, identity.task_id, for_update=True)
                session = read_session(uow.connection, session_id, for_update=True)
                if session.state not in {"awaiting_human", "testing"}:
                    continue
                at = now_utc(uow.connection)
                if at >= session.expires_at or (session.idle_warning_at is not None
                                                and at >= session.idle_warning_at + HUMAN_TEST_IDLE_GRACE):
                    if self.stop is None:
                        raise TaskBoundaryError("human_test_stop_unavailable")
                    _close_wait(uow.connection, session)
                    session = save_session(uow.connection, session, state="expired", ended_at=at)
                    self.stop(uow, session)
                    record_session(uow.connection, session, "human_test.expired")
                elif session.idle_warning_at is None and at >= session.last_human_activity_at + HUMAN_TEST_IDLE_DURATION:
                    session = save_session(uow.connection, session, idle_warning_at=at)
                    record_session(uow.connection, session, "human_test.idle_warning")
                else:
                    continue
                changed.append(session)
            return tuple(changed)
