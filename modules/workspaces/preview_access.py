"""Current preview authorization and single-use transactional redemption."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import func, insert, select, update

from database.commands import lock_and_get, save_result
from database.readiness import assert_schema_ready
from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.facts import read_declaration
from modules.collaboration.guards import check_task_revisions, task_resource
from modules.collaboration.records import reference_key
from modules.identity.actors import AuthoritativeResource, actor_for_command
from modules.identity.authorization import authorize_current
from modules.integration.candidates import _current_input, _read, _ref
from modules.integration.human_test_tables import human_test_sessions
from modules.sync.events import append_event
from modules.workspaces.operations import WorkspaceError, read_workspace_row
from modules.workspaces.preview_access_tables import preview_authorizations, preview_environments
from modules.workspaces.preview_timing import preview_clock
from packages.contracts.p0.decision_common import Contract, Identifier
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p0.preview_contracts import (
    PreviewBinding, PreviewProxyClosure, PreviewRevocation, REVOKE_TIMEOUT_MS, check_client_route, revocation_status,
)
from packages.contracts.p2.human_tests import HumanTestSession
from packages.contracts.p2.previews import (
    PreviewAccessRequest, PreviewAuthenticated, PreviewAuthorizationRecord, PreviewEnvironmentRecord,
    PreviewIssueResult, PreviewLocalClosure, PreviewRedeemResult,
)


class _Issue(Contract):
    environment_id: Identifier
    source_origin: str
    request: PreviewAccessRequest


class _Revoke(Contract):
    authorization_id: Identifier


def _now(connection):
    return connection.scalar(select(func.clock_timestamp()))


def _secret_digest(value: SecretStr):
    return hashlib.sha256(value.get_secret_value().encode("utf-8")).hexdigest()


def _environment(connection, environment_id, *, lock=False):
    query = select(preview_environments).where(preview_environments.c.environment_id == environment_id)
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).mappings().one_or_none()
    if row is None:
        raise WorkspaceError("preview_environment_not_found", status_code=404)
    return PreviewEnvironmentRecord.model_validate(row["record_json"])


def _authorization(connection, authorization_id, *, lock=False):
    query = select(preview_authorizations).where(preview_authorizations.c.authorization_id == authorization_id)
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).mappings().one_or_none()
    if row is None:
        raise WorkspaceError("preview_authorization_not_found", status_code=404)
    return row, PreviewAuthorizationRecord.model_validate(row["record_json"])


def _save(connection, record, **columns):
    connection.execute(update(preview_authorizations).where(
        preview_authorizations.c.authorization_id == record.binding.authorization_id,
    ).values(state=record.state, record_json=record.model_dump(mode="json"), **columns))


def _request_revocation(record, at, clock=preview_clock):
    # Called before commit, so this earlier anchor includes the commit overhead.
    started, evidence = clock.sample()
    revocation = PreviewRevocation(binding=record.binding,
        revoke_revision=record.binding.authorization_revision + 1,
        requested_at=at, deadline_at=at + timedelta(milliseconds=REVOKE_TIMEOUT_MS),
        hub_clock_epoch=clock.epoch, observed_hub_clock_epoch=clock.epoch, elapsed_upper_ms=0,
        timing_evidence_current=evidence is not None, required_proxies=record.required_proxies)
    return record.model_copy(update={"state": "revoking", "revocation": revocation,
        "revocation_started_boottime_ns": started, "revocation_clock_evidence_digest": evidence})


def revoke_environment_in_uow(uow, environment_id, now=None):
    """The lifecycle owns Task/environment locks and its own stop audit event."""
    _environment(uow.connection, environment_id, lock=True)
    rows = uow.connection.execute(select(preview_authorizations).where(
        preview_authorizations.c.environment_id == environment_id,
        preview_authorizations.c.state.in_(("active", "revoking")),
    ).order_by(preview_authorizations.c.authorization_id).with_for_update()).mappings().all()
    at = _now(uow.connection) if now is None else now
    records = []
    for row in rows:
        record = PreviewAuthorizationRecord.model_validate(row["record_json"])
        if record.state == "active":
            record = _request_revocation(record, at)
            _save(uow.connection, record)
        records.append(record)
    return tuple(records)


def _binding(environment, authorization_id, subject_id):
    return PreviewBinding(
        authorization_id=authorization_id, authorization_revision=1, subject_id=subject_id,
        project_id=environment.project_id, environment_ref=environment.environment_ref,
        policy_ref=environment.policy_ref, purpose=environment.purpose, workspace_id=environment.workspace_id,
        candidate_ref=environment.candidate_ref, input_set_ref=environment.input_set_ref,
        artifact_ref=environment.artifact_ref, human_test_session_id=environment.human_test_session_id,
        test_round=environment.test_round,
    )


def _current(uow, actor, task, environment, *, record=None):
    connection = uow.connection
    now = _now(connection)
    if (actor.principal.kind != "human" or environment.project_id != task["project_id"]
            or environment.task_id != task["task_id"] or environment.state != "ready"
            or now >= environment.expires_at
            or task["state"] not in ({"active", "completed"} if environment.purpose == "human_test" else {"active"})
            or task["cancel_requested_at"] is not None
            or task["ordinary_progress_closed"] and task["state"] != "completed"
            or task["input_status"] != "valid"):
        raise WorkspaceError("preview_access_denied", status_code=403)
    if environment.client_route is None:
        raise WorkspaceError("preview_route_unavailable")
    try:
        check_client_route(environment.client_route)
    except ValueError:
        raise WorkspaceError("preview_route_unavailable") from None
    if record is not None and (record.state != "active" or now >= record.expires_at
            or record.environment_revision != environment.revision
            or record.control_revision != task["control_revision"] and task["state"] != "completed"
            or record.input_validity_revision != task["input_validity_revision"]
            or record.binding != _binding(environment, record.binding.authorization_id, actor.principal.subject_id)):
        raise WorkspaceError("preview_access_denied", status_code=403)
    declaration = read_declaration(connection, task)
    policy = declaration.human_test_policy_ref if environment.purpose == "human_test" else declaration.resource_scope_ref
    if environment.policy_ref != policy:
        raise WorkspaceError("preview_policy_stale")
    if environment.purpose == "development":
        workspace = read_workspace_row(connection, environment.workspace_id, for_update=True)
        if (workspace["project_id"], workspace["task_id"]) != (environment.project_id, environment.task_id):
            raise WorkspaceError("preview_workspace_stale")
        return now
    candidate = _read(connection, task, environment.candidate_id)
    candidate_ref = _ref("candidate", candidate.candidate_id, candidate.schema_revision, "integration", candidate)
    if (candidate_ref != environment.candidate_ref or candidate.source_input_set_ref != environment.input_set_ref
            or environment.artifact_ref not in candidate.input_set.references
            or task["control_revision"] != candidate.control_revision and task["state"] != "completed"
            or task["input_validity_revision"] != candidate.input_validity_revision
            or _current_input(connection, task) != reference_key(task["project_id"], candidate.source_input_set_ref)):
        raise WorkspaceError("preview_candidate_stale")
    if environment.purpose == "human_test":
        row = connection.execute(select(human_test_sessions).where(
            human_test_sessions.c.session_id == environment.human_test_session_id,
        ).with_for_update()).mappings().one_or_none()
        if row is None:
            raise WorkspaceError("preview_human_test_stale")
        session = HumanTestSession.model_validate(row["record_json"])
        latest = connection.scalar(select(human_test_sessions.c.session_id).where(
            human_test_sessions.c.task_id == task["task_id"],
        ).order_by(human_test_sessions.c.created_at.desc(), human_test_sessions.c.session_id.desc()).limit(1))
        if (latest != session.session_id or session.project_id != task["project_id"]
                or session.task_id != task["task_id"] or session.state not in {"preparing", "awaiting_human", "testing"}
                or session.tester != actor.principal or session.candidate_id != candidate.candidate_id
                or session.candidate_ref != environment.candidate_ref or session.source_input_set_ref != environment.input_set_ref
                or environment.artifact_ref not in session.artifact_refs or session.policy_ref != environment.policy_ref
                or session.environment_id not in {None, environment.environment_id}
                or session.expires_at is not None and now >= session.expires_at):
            raise WorkspaceError("preview_human_test_stale")
        authorize_current(uow, actor, AuthoritativeResource(
            task["project_id"], "human_test_session", session.session_id, revision=session.revision,
            task_id=task["task_id"],
        ), "human_test.enter")
    return now


class PreviewAccessApplication:
    def __init__(self, engine, control_engine, *, proxy_identity=None, clock=preview_clock):
        self.engine, self.control_engine, self.proxy_identity = engine, control_engine, proxy_identity
        self.clock = clock

    def environment_for_origin(self, target_origin):
        with UnitOfWork(self.control_engine) as uow:
            environment_id = uow.connection.scalar(select(preview_environments.c.environment_id).where(
                preview_environments.c.entry_origin == target_origin))
            if environment_id is None:
                raise WorkspaceError("preview_environment_not_found", status_code=404)
            return _environment(uow.connection, environment_id)

    def issue(self, actor, environment_id, request: PreviewAccessRequest, key, source_origin):
        if actor.principal.kind != "human" or actor.authentication_source != "device_session":
            raise WorkspaceError("preview_human_required", status_code=403)
        with UnitOfWork(self.engine) as uow:
            initial = _environment(uow.connection, environment_id)
            task, authorization = lock_task_access(uow, actor, initial.task_id, "resource.read")
            environment = _environment(uow.connection, environment_id, lock=True)
            resource = task_resource(task)
            intent = CommandIntent(request_schema_revision="p2-preview-issue-r1", caller=actor.principal,
                scope=resource.scope, target=resource.target_scope, action="resource.read",
                expected_resource_revision=request.expected_version)
            command = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex, idempotency_key=key,
                request_digest=request_digest(intent, _Issue(environment_id=environment_id,
                    source_origin=source_origin, request=request)))
            existing = lock_and_get(uow.connection, command)
            if existing is not None:
                result = PreviewAuthorizationRecord.model_validate(existing.result)
                _, current = _authorization(uow.connection, result.binding.authorization_id)
                return PreviewIssueResult(current)
            assert_schema_ready(uow.connection)
            check_task_revisions(task, expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision)
            now = _current(uow, actor, task, environment)
            if (source_origin != environment.management_origin or environment.revision != request.expected_environment_revision
                    or not now < request.expires_at <= environment.expires_at):
                raise WorkspaceError("preview_request_binding_invalid")
            existing_open = uow.connection.scalar(select(preview_authorizations.c.authorization_id).where(
                preview_authorizations.c.environment_id == environment_id,
                preview_authorizations.c.subject_id == actor.principal.subject_id,
                preview_authorizations.c.state.in_(("active", "revoking"))).limit(1))
            if existing_open is not None:
                raise WorkspaceError("preview_previous_authorization_open")
            ticket = SecretStr(secrets.token_urlsafe(32))
            record = PreviewAuthorizationRecord(command_id=command.command_id, environment_id=environment_id,
                environment_revision=environment.revision,
                binding=_binding(environment, "preview-auth-" + command.command_id, actor.principal.subject_id),
                control_revision=task["control_revision"], input_validity_revision=task["input_validity_revision"],
                issued_at=now, expires_at=request.expires_at, ticket_expires_at=min(now + timedelta(seconds=60), request.expires_at),
                required_proxies=environment.required_proxies)
            uow.connection.execute(insert(preview_authorizations).values(
                authorization_id=record.binding.authorization_id, environment_id=environment_id,
                subject_id=record.binding.subject_id, command_id=command.command_id, state=record.state,
                ticket_digest=_secret_digest(ticket), record_json=record.model_dump(mode="json")))
            save_result(uow.connection, command, record, status_code=201, authorization=authorization.envelope)
            append_event(uow.connection, command_id=command.command_id, project_id=task["project_id"],
                aggregate_kind="preview_authorization", aggregate_id=record.binding.authorization_id,
                aggregate_version=1, event_type="preview.authorization_issued", schema_version="p2-preview-access-r1",
                payload=record)
            return PreviewIssueResult(record, ticket)

    def redeem(self, origin, target_origin, secret: SecretStr):
        with UnitOfWork(self.engine) as uow:
            authorization_id = uow.connection.scalar(select(preview_authorizations.c.authorization_id).where(
                preview_authorizations.c.ticket_digest == _secret_digest(secret)))
            if authorization_id is None:
                raise WorkspaceError("preview_access_denied", status_code=403)
            _, initial = _authorization(uow.connection, authorization_id)
            environment = _environment(uow.connection, initial.environment_id)
            actor = actor_for_command(uow, initial.command_id)
            task, _ = lock_task_access(uow, actor, environment.task_id, "resource.read")
            environment = _environment(uow.connection, initial.environment_id, lock=True)
            _, record = _authorization(uow.connection, authorization_id, lock=True)
            now = _current(uow, actor, task, environment, record=record)
            if (origin != environment.management_origin or target_origin != environment.entry_origin
                    or record.ticket_state != "unused" or now >= record.ticket_expires_at):
                raise WorkspaceError("preview_access_denied", status_code=403)
            cookie = SecretStr(secrets.token_urlsafe(32))
            record = record.model_copy(update={"ticket_state": "consumed", "redemption_id": "redemption-" + uuid4().hex,
                                               "session_id": "preview-session-" + uuid4().hex})
            _save(uow.connection, record, session_digest=_secret_digest(cookie))
            return PreviewRedeemResult(record, record.session_id, cookie)

    def authenticate(self, cookie: SecretStr, environment_id):
        with UnitOfWork(self.control_engine) as uow:
            authorization_id = uow.connection.scalar(select(preview_authorizations.c.authorization_id).where(
                preview_authorizations.c.session_digest == _secret_digest(cookie)))
            if authorization_id is None:
                raise WorkspaceError("preview_access_denied", status_code=403)
            _, initial = _authorization(uow.connection, authorization_id)
            environment = _environment(uow.connection, initial.environment_id)
            actor = actor_for_command(uow, initial.command_id)
            task, _ = lock_task_access(uow, actor, environment.task_id, "resource.read")
            environment = _environment(uow.connection, initial.environment_id, lock=True)
            _, record = _authorization(uow.connection, authorization_id, lock=True)
            _current(uow, actor, task, environment, record=record)
            if environment_id != environment.environment_id or record.ticket_state != "consumed":
                raise WorkspaceError("preview_access_denied", status_code=403)
            return PreviewAuthenticated(record, environment)

    def query(self, actor, authorization_id):
        with UnitOfWork(self.control_engine) as uow:
            _, initial = _authorization(uow.connection, authorization_id)
            environment = _environment(uow.connection, initial.environment_id)
            lock_task_access(uow, actor, environment.task_id, "resource.read")
            if actor.principal.kind != "human" or actor.principal.subject_id != initial.binding.subject_id:
                raise WorkspaceError("preview_authorization_not_found", status_code=404)
            return self.clock.observe(_authorization(uow.connection, authorization_id)[1])

    def revoke(self, actor, authorization_id, key):
        if actor.principal.kind != "human" or actor.authentication_source != "device_session":
            raise WorkspaceError("preview_human_required", status_code=403)
        with UnitOfWork(self.engine) as uow:
            _, initial = _authorization(uow.connection, authorization_id)
            environment = _environment(uow.connection, initial.environment_id)
            task, authorization = lock_task_access(uow, actor, environment.task_id, "resource.read")
            environment = _environment(uow.connection, initial.environment_id, lock=True)
            _, record = _authorization(uow.connection, authorization_id, lock=True)
            if record.binding.subject_id != actor.principal.subject_id:
                raise WorkspaceError("preview_authorization_not_found", status_code=404)
            resource = task_resource(task)
            intent = CommandIntent(request_schema_revision="p2-preview-revoke-r1", caller=actor.principal,
                scope=resource.scope, target=resource.target_scope, action="resource.read", expected_resource_revision=0)
            command = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex, idempotency_key=key,
                request_digest=request_digest(intent, _Revoke(authorization_id=authorization_id)))
            existing = lock_and_get(uow.connection, command)
            if existing is not None:
                return record
            if record.state == "active":
                record = _request_revocation(record, _now(uow.connection), self.clock)
                _save(uow.connection, record)
                append_event(uow.connection, command_id=command.command_id, project_id=task["project_id"],
                    aggregate_kind="preview_authorization", aggregate_id=authorization_id, aggregate_version=2,
                    event_type="preview.revocation_requested", schema_version="p2-preview-access-r1", payload=record)
            save_result(uow.connection, command, record, status_code=200, authorization=authorization.envelope)
            return record

    def pending_revocations(self, proxy):
        with UnitOfWork(self.control_engine) as uow:
            rows = uow.connection.scalars(select(preview_authorizations.c.record_json).where(
                preview_authorizations.c.state == "revoking"))
            records = (self.clock.observe(PreviewAuthorizationRecord.model_validate(row)) for row in rows)
            return tuple(record for record in records if any(
                item.proxy_id == proxy.proxy_id for item in record.revocation.required_proxies))

    def record_local_proxy_closure(self, authorization_id, proxy, denied_at, closed_at,
                                   client_connections, upstream_connections):
        fact = PreviewLocalClosure(proxy=proxy, denied_at=denied_at, closed_at=closed_at,
            client_connections=client_connections, upstream_connections=upstream_connections)
        with UnitOfWork(self.engine) as uow:
            _, record = _authorization(uow.connection, authorization_id, lock=True)
            if record.revocation is None or proxy not in record.revocation.required_proxies:
                raise WorkspaceError("preview_proxy_closure_binding_invalid")
            existing = next((item for item in record.local_closures if item.proxy == proxy), None)
            if existing is not None and existing.model_copy(update={"transport_receipt_digest": None}) != fact:
                raise WorkspaceError("preview_proxy_closure_conflict")
            closures = record.local_closures if existing is not None else (*record.local_closures, fact)
            record = record.model_copy(update={"local_closures": closures})
            _save(uow.connection, record)
            return record

    def record_proxy_transport_closure(self, authorization_id, proxy, receipt):
        """Only the controlled TLS listener's physical receipt can close its external route."""
        owner = receipt["transport_owner"]
        denied, closed = receipt["denied"], receipt["closed"]
        if (not owner["external_tls"] or owner["started"] is None
                or proxy != self.proxy_identity or receipt["client_connections"] != 0
                or receipt["upstream_connections"] != 0
                or not owner["started"]["boottime"] <= denied["boottime"] <= closed["boottime"]):
            raise WorkspaceError("preview_transport_closure_invalid")
        for connection in receipt["connections"]:
            downstream, upstream = connection["downstream"], connection["upstream"]
            if (not downstream["external_tls"] or downstream["connection_lost"] is None
                    or upstream is not None and upstream["descriptor_closed"] is None):
                raise WorkspaceError("preview_transport_closure_invalid")
        digest = "sha256:" + hashlib.sha256(json.dumps(receipt, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        with UnitOfWork(self.engine) as uow:
            _, record = _authorization(uow.connection, authorization_id, lock=True)
            revocation = record.revocation
            if revocation is None or proxy not in revocation.required_proxies:
                raise WorkspaceError("preview_proxy_closure_binding_invalid")
            previous = next((item for item in record.local_closures if item.proxy == proxy), None)
            fact = PreviewLocalClosure(proxy=proxy, denied_at=datetime.fromisoformat(denied["utc"]),
                closed_at=datetime.fromisoformat(closed["utc"]), client_connections=0,
                upstream_connections=0, transport_receipt_digest=digest)
            if previous is not None and previous.transport_receipt_digest is not None and previous != fact:
                raise WorkspaceError("preview_proxy_closure_conflict")
            if previous != fact:
                record = record.model_copy(update={"local_closures": tuple(
                    item for item in record.local_closures if item.proxy != proxy) + (fact,)})
                _save(uow.connection, record)
            existing = next((item for item in revocation.closures if item.proxy == proxy), None)
            if existing is not None:
                return record
            observed = self.clock.observe(record)
            closure = PreviewProxyClosure(proxy=proxy, binding=record.binding,
                revoke_revision=revocation.revoke_revision, hub_clock_epoch=revocation.hub_clock_epoch,
                received_elapsed_upper_ms=observed.revocation.elapsed_upper_ms, new_access_denied=True,
                all_routes_closed=True, sessions_disabled=True, remaining_client_connections=0,
                remaining_upstream_connections=0, denied_at=fact.denied_at, connections_closed_at=fact.closed_at)
        return self.confirm_proxy_closure(authorization_id, closure)

    def confirm_proxy_closure(self, authorization_id, closure: PreviewProxyClosure):
        with UnitOfWork(self.engine) as uow:
            _, record = _authorization(uow.connection, authorization_id, lock=True)
            if record.revocation is None:
                raise WorkspaceError("preview_proxy_closure_binding_invalid")
            record = self.clock.observe(record)
            revocation = record.revocation
            previous = next((item for item in revocation.closures if item.proxy == closure.proxy), None)
            if previous is not None and previous != closure:
                raise WorkspaceError("preview_proxy_closure_conflict")
            if previous is None:
                revocation = PreviewRevocation.model_validate({**revocation.model_dump(),
                    "closures": (*revocation.closures, closure),
                    "elapsed_upper_ms": max(revocation.elapsed_upper_ms, closure.received_elapsed_upper_ms)})
                record = record.model_copy(update={"revocation": revocation})
            if revocation_status(revocation) in {"effective", "effective_late"}:
                record = record.model_copy(update={"state": "revoked"})
            _save(uow.connection, record)
            return record
