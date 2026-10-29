"""Preview intent transactions; physical work stays in the existing worker/Runner."""

import hashlib
import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from pydantic import Field
from sqlalchemy import func, insert, select, update

from database.commands import lock_and_get, save_result
from database.uow import UnitOfWork
from modules.collaboration.command_support import TaskCommandContext, lock_task_access, update_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_declaration
from modules.collaboration.guards import check_task_revisions, require_ordinary_progress, task_resource
from modules.integration.candidates import _read, _ref
from modules.sync.events import append_event
from modules.workspaces.preview_access import _environment, revoke_environment_in_uow
from modules.workspaces.preview_access_tables import preview_authorizations, preview_environments
from modules.workspaces.preview_environment_tables import preview_environment_intents as intents
from modules.workspaces.preview_profiles import fixed_preview_inputs
from packages.contracts.p0.decision_common import Contract
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import CommandEnvelope, CommandIntent, request_digest
from packages.contracts.p0.preview_contracts import PreviewClientRoute, check_client_route, revocation_status
from packages.contracts.p2.preview_environments import PreviewEnvironmentResult, PreviewEnvironmentView
from packages.contracts.p2.previews import PreviewAuthorizationRecord, PreviewEnvironmentRecord, PreviewUpstream
from packages.contracts.p1.task_facts import EnvironmentMetadata, RegisteredReference
from packages.contracts.p1.resource_protocol import canonical_digest


class PreviewInstallation(Contract):
    management_origin: str = Field(max_length=512)
    preview_domain: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9.-]{0,250}[a-z0-9])?$")
    client_route: PreviewClientRoute


def installation_descriptor():
    """The optional file contains public installation/evidence metadata only."""
    path = os.environ.get("CLOUDHELM_PREVIEW_DESCRIPTOR")
    if not path:
        return None
    descriptor = PreviewInstallation.model_validate_json(Path(path).read_text(encoding="utf-8"))
    check_client_route(descriptor.client_route)
    return descriptor


def save_environment(connection, record):
    connection.execute(update(preview_environments).where(
        preview_environments.c.environment_id == record.environment_id,
    ).values(state=record.state, entry_origin=record.entry_origin, record_json=record.model_dump(mode="json")))


def _intent(connection, operation_id):
    row = connection.execute(select(intents).where(intents.c.operation_id == operation_id)).mappings().one_or_none()
    if row is None:
        raise TaskBoundaryError("preview_intent_not_found", status_code=404)
    return row


class PreviewEnvironmentApplication:
    def __init__(self, engine, control_engine, *, enqueue=None, proxy_identity=None, load_installation=True):
        self.engine, self.control_engine = engine, control_engine
        self.enqueue, self.proxy_identity = enqueue, proxy_identity
        self.installation = installation_descriptor() if load_installation else None

    def _enqueue(self, uow, record, command_id, action, payload, *, operation_id=None):
        operation_id = operation_id or record.environment_id
        if uow.connection.scalar(select(intents.c.operation_id).where(intents.c.operation_id == operation_id)):
            return
        uow.connection.execute(insert(intents).values(operation_id=operation_id, environment_id=record.environment_id,
            command_id=command_id, action=action, request_json=payload, reason="preview_queued"))
        if self.enqueue is None:
            raise TaskBoundaryError("preview_worker_not_configured")
        self.enqueue(uow, operation_id, command_id, record.environment_id, record.revision,
                      "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest())

    def _create(self, uow, context, *, candidate=None, session=None, development=None):
        task = context.task
        if development is not None:
            environment_id = development["environment_id"]
            if uow.connection.scalar(select(preview_environments.c.environment_id).where(
                    preview_environments.c.environment_id == environment_id)):
                raise TaskBoundaryError("preview_development_already_registered")
        elif session is None:
            environment_id = "candidate-preview-" + uuid4().hex
        else:
            environment_id = "candidate-preview-" + hashlib.sha256(session.session_id.encode()).hexdigest()[:32]
        if session is not None and uow.connection.scalar(select(preview_environments.c.environment_id).where(
                preview_environments.c.environment_id == environment_id)):
            return _environment(uow.connection, environment_id)
        declaration = read_declaration(uow.connection, task)
        purpose = "human_test" if session is not None else "development" if development else "candidate"
        details = {"environment_id": environment_id, "purpose": purpose,
                   "candidate_id": candidate.candidate_id if candidate else None,
                   "session_id": session.session_id if session else None,
                   "prepare_operation_id": development["operation_id"] if development else None}
        ref = EngineeringRef(kind="environment", object_id=environment_id, revision="1", authority="integration",
                             digest=canonical_digest(details), digest_algorithm="sha256")
        now = uow.connection.scalar(select(func.clock_timestamp()))
        record = PreviewEnvironmentRecord(environment_id=environment_id, project_id=task["project_id"],
            task_id=task["task_id"], purpose=purpose, revision=1, environment_ref=ref,
            policy_ref=declaration.human_test_policy_ref if session else declaration.resource_scope_ref,
            expires_at=now + timedelta(hours=6), state="preparing", resource_reservation_id=None,
            workspace_id=development["workspace_id"] if development else None,
            candidate_id=candidate.candidate_id if candidate else None,
            candidate_ref=_ref("candidate", candidate.candidate_id, candidate.schema_revision, "integration", candidate) if candidate else None,
            input_set_ref=candidate.source_input_set_ref if candidate else None,
            artifact_ref=next((r for r in candidate.input_set.references
                               if r.kind == "artifact" and r.authority == "artifacts"), None) if candidate else None,
            human_test_session_id=session.session_id if session else None, test_round=1 if session else None)
        uow.connection.execute(insert(preview_environments).values(environment_id=environment_id,
            project_id=task["project_id"], task_id=task["task_id"], state=record.state,
            entry_origin=None, record_json=record.model_dump(mode="json")))
        payload = details | {"control_revision": task["control_revision"],
                             "input_validity_revision": task["input_validity_revision"]}
        self._enqueue(uow, record, context.envelope.command_id, "prepare", payload)
        append_event(uow.connection, command_id=context.envelope.command_id, project_id=record.project_id,
                     aggregate_kind="preview", aggregate_id=environment_id, aggregate_version=1,
                     event_type="preview.requested", schema_version="p2-preview-r1", payload=record)
        return record

    def prepare_human(self, uow, context, session):
        candidate = _read(uow.connection, context.task, session.candidate_id)
        return self._create(uow, context, candidate=candidate, session=session)

    def start(self, actor, task_id, request, *, idempotency_key, development=False):
        with UnitOfWork(self.engine) as uow:
            task, authorization = lock_task_access(uow, actor, task_id, "task.command")
            intent = CommandIntent(request_schema_revision="p2-preview-r1", caller=actor.principal,
                scope=task_resource(task).scope, target=task_resource(task).target_scope,
                action="task.command", expected_resource_revision=request.expected_version)
            envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex,
                idempotency_key=idempotency_key, request_digest=request_digest(intent, request))
            existing = lock_and_get(uow.connection, envelope)
            if existing:
                return PreviewEnvironmentResult.model_validate(existing.result)
            require_ordinary_progress(uow.connection, task_id, expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision)
            context = TaskCommandContext(uow, actor, task, authorization, envelope)
            if development:
                from modules.workspaces.development_queries import read_development_operation_record

                _, client_request, row, _, _ = read_development_operation_record(uow.connection, request.prepare_operation_id)
                if row["task_id"] != task_id or not client_request.preview or client_request.action != "prepare":
                    raise TaskBoundaryError("preview_development_operation_invalid")
                record = self._create(uow, context, development={"operation_id": request.prepare_operation_id,
                    "environment_id": row["environment_id"], "workspace_id": row["workspace_id"]})
            else:
                candidate = _read(uow.connection, task, request.candidate_id)
                fixed_preview_inputs(uow.connection, candidate)
                record = self._create(uow, context, candidate=candidate)
            update_task(context)
            result = PreviewEnvironmentResult(command_id=envelope.command_id, environment=self.view(uow, record))
            save_result(uow.connection, envelope, result, status_code=202, authorization=authorization.envelope)
            return result

    def view(self, uow, record):
        reason = uow.connection.scalar(select(intents.c.reason).where(
            intents.c.environment_id == record.environment_id).order_by(intents.c.updated_at.desc()).limit(1))
        grants = uow.connection.scalars(select(preview_authorizations.c.record_json).where(
            preview_authorizations.c.environment_id == record.environment_id)).all()
        statuses = [revocation_status(PreviewAuthorizationRecord.model_validate(value).revocation)
                    for value in grants if value.get("revocation")]
        return PreviewEnvironmentView(environment_id=record.environment_id, purpose=record.purpose,
            state=record.state, actual_revision=record.actual_revision,
            resource_reservation_id=record.resource_reservation_id, expires_at=record.expires_at.isoformat(),
            reason=reason, revocation_status=",".join(sorted(set(statuses))) or None,
            management_start_url=(self.installation.management_origin + "/preview/start/" + record.environment_id
                                  if self.installation else None))

    def query(self, actor, environment_id):
        with UnitOfWork(self.control_engine) as uow:
            initial = _environment(uow.connection, environment_id)
            lock_task_access(uow, actor, initial.task_id, "resource.read")
            return self.view(uow, self.refresh_in_uow(uow, environment_id))

    def stop(self, actor, environment_id, request, *, idempotency_key):
        with UnitOfWork(self.control_engine) as uow:
            initial = _environment(uow.connection, environment_id)
            task, authorization = lock_task_access(uow, actor, initial.task_id, "operation.stop")
            record = _environment(uow.connection, environment_id, lock=True)
            resource = task_resource(task)
            intent = CommandIntent(request_schema_revision="p2-preview-stop-r1", caller=actor.principal,
                scope=resource.scope, target=resource.target_scope, action="operation.stop",
                expected_resource_revision=request.expected_version)
            envelope = CommandEnvelope(**intent.model_dump(), command_id=uuid4().hex,
                idempotency_key=idempotency_key, request_digest=request_digest(intent, request))
            previous = lock_and_get(uow.connection, envelope)
            if previous is not None:
                return PreviewEnvironmentResult.model_validate(previous.result)
            check_task_revisions(task, expected_version=request.expected_version,
                expected_control_revision=request.expected_control_revision,
                expected_input_validity_revision=request.expected_input_validity_revision)
            if request.expected_environment_revision != record.revision:
                raise TaskBoundaryError("preview_environment_revision_conflict")
            self.stop_in_uow(uow, record, envelope.command_id)
            result = PreviewEnvironmentResult(command_id=envelope.command_id,
                environment=self.view(uow, _environment(uow.connection, environment_id)))
            save_result(uow.connection, envelope, result, status_code=202, authorization=authorization.envelope)
            return result

    def refresh_in_uow(self, uow, environment_id):
        record = _environment(uow.connection, environment_id, lock=True)
        if record.state in {"stopping", "stopped", "failed"}:
            return record
        row = uow.connection.execute(select(intents).where(intents.c.environment_id == environment_id,
            intents.c.action == "prepare")).mappings().one()
        observation = row["request_json"].get("observation", {})
        if not observation.get("ready"):
            return record
        from modules.collaboration.guards import read_task
        from modules.collaboration.records import reference_key
        from modules.integration.candidates import _current_input

        task = read_task(uow.connection, record.task_id)
        payload = row["request_json"]
        if (task["cancel_requested_at"] is not None or task["input_status"] != "valid"
                or task["input_validity_revision"] != payload["input_validity_revision"]
                or task["control_revision"] != payload["control_revision"] and task["state"] != "completed"
                or task["state"] == "completed" and record.purpose != "human_test"):
            return record
        if record.candidate_id is not None and _current_input(uow.connection, task) != reference_key(
                record.project_id, record.input_set_ref):
            return record
        descriptor = self.installation
        if descriptor is None or self.proxy_identity is None:
            return record
        upstreams = tuple(PreviewUpstream(service=service, host=target.get("ipv4", target.get("host")),
                                         port=target["port"])
                          for service, target in observation["targets"].items())
        # The immutable reference describes what actually ran, including fixed test data.
        facts = {"environment_id": record.environment_id, "purpose": record.purpose,
                 "candidate_id": record.candidate_id, "actual_revision": observation["actual_revision"],
                 "data_revision": observation.get("data_revision"), "profile": "p2-preview-r1"}
        metadata = EnvironmentMetadata(description="Controlled preview runtime " + record.environment_id,
                                       support_scope=("human_test",) if record.purpose == "human_test" else ("development_preview",))
        if record.purpose == "human_test":
            metadata = metadata.model_copy(update={"description": metadata.description + "; facts=" +
                                                    hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()})
        environment_ref = _ref("environment", record.environment_id, "1", "integration", metadata)
        entry_origin = "https://" + record.environment_id + "." + descriptor.preview_domain
        changes = {"state": "ready", "actual_revision": observation["actual_revision"],
                   "resource_reservation_id": observation["reservation_id"], "environment_ref": environment_ref,
                   "entry_origin": entry_origin, "management_origin": descriptor.management_origin,
                   "client_route": descriptor.client_route, "required_proxies": (self.proxy_identity,),
                   "upstreams": upstreams}
        if record.state != "ready":
            now = uow.connection.scalar(select(func.clock_timestamp()))
            from datetime import datetime

            resource_deadline = datetime.fromisoformat(observation["resource_deadline"])
            changes["expires_at"] = min(now + timedelta(hours=6 if record.purpose == "human_test" else 4), resource_deadline)
        changed = PreviewEnvironmentRecord.model_validate(record.model_copy(update=changes).model_dump())
        if changed != record:
            if record.state == "ready" and (changed.environment_ref != record.environment_ref
                    or changed.required_proxies != record.required_proxies or changed.upstreams != record.upstreams):
                revoke_environment_in_uow(uow, environment_id)
                changed = changed.model_copy(update={"revision": record.revision + 1})
            save_environment(uow.connection, changed)
        return changed

    def readiness(self, uow, actor, session):
        row = uow.connection.scalar(select(preview_environments.c.record_json).where(
            preview_environments.c.task_id == session.task_id,
            preview_environments.c.record_json["human_test_session_id"].astext == session.session_id))
        if row is None:
            raise TaskBoundaryError("human_test_preview_not_ready")
        record = self.refresh_in_uow(uow, row["environment_id"])
        now = uow.connection.scalar(select(func.clock_timestamp()))
        grants = uow.connection.scalars(select(preview_authorizations.c.record_json).where(
            preview_authorizations.c.environment_id == record.environment_id,
            preview_authorizations.c.subject_id == actor.principal.subject_id,
            preview_authorizations.c.state == "active")).all()
        if (record.state != "ready" or now >= record.expires_at
                or not any(value["environment_revision"] == record.revision
                           and PreviewAuthorizationRecord.model_validate(value).expires_at > now for value in grants)):
            raise TaskBoundaryError("human_test_preview_not_ready")
        from modules.collaboration.records import _store_reference, read_registered_reference
        from modules.identity.actors import AuthoritativeResource
        from modules.identity.authorization import authorize_current
        from modules.integration.validity import selected_verification
        import rfc8785

        task, _ = lock_task_access(uow, actor, session.task_id, "resource.read")
        proof = read_registered_reference(uow.connection, session.project_id,
                                          selected_verification(uow.connection, task).evidence_ref)
        auth = authorize_current(uow, actor, AuthoritativeResource(session.project_id, "human_test_session",
            session.session_id, revision=session.revision, task_id=session.task_id), "human_test.enter")
        facts = {"environment_id": record.environment_id, "purpose": record.purpose,
                 "candidate_id": record.candidate_id, "actual_revision": record.actual_revision,
                 "data_revision": uow.connection.scalar(select(intents.c.request_json).where(
                     intents.c.environment_id == record.environment_id, intents.c.action == "prepare"))["observation"].get("data_revision"),
                 "profile": "p2-preview-r1"}
        metadata = EnvironmentMetadata(description="Controlled preview runtime " + record.environment_id + "; facts=" +
            hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest(), support_scope=("human_test",))
        registration = RegisteredReference(project_id=session.project_id, registration_id="preview-runtime-" + record.environment_id,
            source_id=proof.source_id, source_record_id=record.environment_id, reference=record.environment_ref,
            metadata=metadata, observed_at_utc=now)
        from modules.collaboration.records import reference_key
        from modules.collaboration.tables import task_reference_records

        exists = uow.connection.scalar(select(task_reference_records.c.reference_key).where(
            task_reference_records.c.reference_key == reference_key(session.project_id, record.environment_ref)))
        if exists is None:
            _store_reference(uow.connection, registration, rfc8785.dumps(metadata.model_dump(mode="json")), auth.envelope)
        elif read_registered_reference(uow.connection, session.project_id, record.environment_ref).metadata != metadata:
            raise TaskBoundaryError("human_test_runtime_evidence_changed")
        return record.environment_id, record.environment_ref

    def stop_human(self, uow, session):
        values = uow.connection.scalars(select(preview_environments.c.record_json).where(
            preview_environments.c.record_json["human_test_session_id"].astext == session.session_id)).all()
        for value in values:
            self.stop_in_uow(uow, PreviewEnvironmentRecord.model_validate(value), session.command_id)

    def stop_in_uow(self, uow, record, command_id):
        if record.state in {"stopping", "stopped"}:
            return
        revoke_environment_in_uow(uow, record.environment_id)
        record = record.model_copy(update={"state": "stopping", "revision": record.revision + 1})
        save_environment(uow.connection, record)
        self._enqueue(uow, record, command_id, "stop", {},
                      operation_id="preview-stop-" + hashlib.sha256(record.environment_id.encode()).hexdigest()[:32])
        append_event(uow.connection, command_id=command_id, project_id=record.project_id,
            aggregate_kind="preview", aggregate_id=record.environment_id, aggregate_version=record.revision,
            event_type="preview.stop_requested", schema_version="p2-preview-r1", payload=self.view(uow, record))

    def can_renew(self, uow, session):
        from modules.execution.tables import resource_reservations
        from packages.contracts.p0.resource_contracts import ResourceAllocation

        record = uow.connection.scalar(select(preview_environments.c.record_json).where(
            preview_environments.c.record_json["human_test_session_id"].astext == session.session_id))
        if record is None:
            return False
        environment = PreviewEnvironmentRecord.model_validate(record)
        value = uow.connection.scalar(select(resource_reservations.c.allocation_json).where(
            resource_reservations.c.reservation_id == environment.resource_reservation_id))
        return bool(value and ResourceAllocation.model_validate(value).state == "active"
                    and environment.state == "ready" and session.ready_at is not None
                    and environment.expires_at >= session.ready_at + timedelta(hours=6))
