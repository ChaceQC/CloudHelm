"""P0 app-owned wait/resume transaction joined to DBOS enqueue."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from dbos import DBOS, DBOSClient, EnqueueOptions
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    func,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateSchema

from integrations.seam_admission import (
    AdmissionError,
    AdmissionStorageError,
    ExecutionScope,
    GateDenied,
    SeamAdmission,
)

SCHEMA = "p0_continuation"
WORKFLOW_NAME = "p0.a01.continuation"
_HEX_DIGEST = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")

_metadata = MetaData(schema=SCHEMA)
sessions = Table(
    "sessions",
    _metadata,
    Column("session_id", String(240), primary_key=True),
    Column("task_id", String(240), nullable=False),
    Column("status", String(24), nullable=False),
    Column("current_run_id", String(240), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
runs = Table(
    "runs",
    _metadata,
    Column("run_id", String(240), primary_key=True),
    Column("task_id", String(240), nullable=False),
    Column("session_id", String(240), ForeignKey(f"{SCHEMA}.sessions.session_id"), nullable=False),
    Column("status", String(24), nullable=False),
    Column("outcome", String(48), nullable=True),
    Column("result_ref", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
waits = Table(
    "waits",
    _metadata,
    Column("wait_id", String(240), primary_key=True),
    Column("wait_digest", String(64), nullable=False),
    Column("task_id", String(240), nullable=False),
    Column("session_id", String(240), ForeignKey(f"{SCHEMA}.sessions.session_id"), nullable=False),
    Column("original_run_id", String(240), nullable=False),
    Column("control_revision", String(160), nullable=False),
    Column("permission_revision", String(160), nullable=False),
    Column("input_revision", String(160), nullable=False),
    Column("operation_id", String(240), nullable=False),
    Column("operation_digest", String(64), nullable=False),
    Column("checkpoint_ref", String(512), nullable=False),
    Column("accepted_receipt", JSONB, nullable=False),
    Column("result_ref", JSONB, nullable=True),
    Column("outcome", String(48), nullable=False),
    Column("status", String(24), nullable=False),
    Column("resume_digest", String(64), nullable=True),
    Column("new_run_id", String(240), nullable=True),
    Column("workflow_id", String(240), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("original_run_id", name="uq_continuation_wait_original_run"),
)
events = Table(
    "events",
    _metadata,
    Column("event_id", String(240), primary_key=True),
    Column("wait_id", String(240), ForeignKey(f"{SCHEMA}.waits.wait_id"), nullable=False),
    Column("event_type", String(64), nullable=False),
    Column("event_digest", String(64), nullable=False),
    Column("event_refs", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
workflow_bindings = Table(
    "workflow_bindings",
    _metadata,
    Column("workflow_id", String(240), primary_key=True),
    Column("wait_id", String(240), ForeignKey(f"{SCHEMA}.waits.wait_id"), nullable=False, unique=True),
    Column("task_id", String(240), nullable=False),
    Column("session_id", String(240), nullable=False),
    Column("run_id", String(240), nullable=False, unique=True),
    Column("workflow_name", String(160), nullable=False),
    Column("queue_name", String(160), nullable=False),
    Column("application_name", String(160), nullable=False),
    Column("code_version", String(80), nullable=False),
    Column("request_digest", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class ContinuationError(RuntimeError):
    """Base class for bounded continuation failures."""


class ContinuationConflict(ContinuationError):
    """A stable wait or resume identity was reused with different inputs."""


class WaitNotFound(ContinuationError):
    """The requested wait identity is not present."""


class WaitPending(ContinuationError):
    """The referenced operation does not yet have a queryable final result."""


class InjectedContinuationFailure(ContinuationError):
    """A test failure injected after a transactional boundary."""


def _workflow_result(payload_json: str) -> dict[str, str]:
    payload = json.loads(payload_json)
    allowed = {
        "task_id",
        "session_id",
        "new_run_id",
        "operation_id",
        "operation_digest",
        "checkpoint_ref",
        "result_ref_digest",
        "resume_digest",
    }
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise ValueError("continuation workflow input does not match its bounded schema")
    if any(not isinstance(payload[key], str) for key in allowed):
        raise ValueError("continuation workflow input contains a non-string field")
    return payload


def _validated_workflow_result(
    value: Mapping[str, Any], wait: Mapping[str, Any]
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ContinuationConflict("public DBOS result must be a reference mapping")
    expected = {
        "task_id": wait["task_id"],
        "session_id": wait["session_id"],
        "new_run_id": wait["new_run_id"],
        "operation_id": wait["operation_id"],
        "operation_digest": wait["operation_digest"],
        "checkpoint_ref": wait["checkpoint_ref"],
        "result_ref_digest": _document_digest(wait["result_ref"]),
        "resume_digest": wait["resume_digest"],
    }
    if set(value) != set(expected) or any(
        type(value.get(key)) is not str or value[key] != expected[key]
        for key in expected
    ):
        raise ContinuationConflict("public DBOS result does not match the fixed continuation references")
    return dict(expected)


@DBOS.workflow(name=WORKFLOW_NAME)
def continuation_workflow(payload_json: str) -> dict[str, str]:
    """Return bounded references for the new Run; no message history is included."""
    return _workflow_result(payload_json)


class SeamContinuation:
    """Persist wait/Run/event/binding state with a DBOS transactional enqueue."""

    def __init__(
        self,
        admission: SeamAdmission,
        client: DBOSClient,
        *,
        application_name: str,
        code_version: str,
        queue_name: str,
    ) -> None:
        self.admission = admission
        self.engine: Engine = admission.engine
        self.client = client
        self.application_name = _identity(application_name, "application_name")
        self.code_version = _identity(code_version, "code_version")
        self.queue_name = _identity(queue_name, "queue_name")

    def bootstrap(self) -> None:
        """Create only the app-owned continuation schema; never reset it."""
        try:
            with self.engine.begin() as connection:
                connection.execute(CreateSchema(SCHEMA, if_not_exists=True))
                _metadata.create_all(connection)
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "could not bootstrap the isolated continuation schema; database details are suppressed"
            ) from None

    def record_wait(
        self,
        scope: ExecutionScope,
        *,
        operation_id: str,
        operation_digest: str,
        accepted_receipt: Mapping[str, Any],
        checkpoint_ref: str,
        gateway_result_ref: Mapping[str, Any] | None = None,
        wait_id: str | None = None,
    ) -> dict[str, Any]:
        """Close the original Run into waiting_condition with bounded references."""
        operation_id = _identity(operation_id, "operation_id")
        operation_digest = _digest(operation_digest)
        receipt = _accepted_receipt(accepted_receipt, operation_id, operation_digest)
        checkpoint_ref = _identity(checkpoint_ref, "checkpoint_ref", maximum=512)
        result_ref = _result_ref(gateway_result_ref, operation_id)
        if result_ref is not None:
            result_ref = _json_safe(result_ref)
        core = {
            "task_id": _scope_identity(scope, "task_id"),
            "session_id": _scope_identity(scope, "session_id"),
            "original_run_id": _scope_identity(scope, "run_id"),
            "control_revision": _revision(scope.control_revision),
            "permission_revision": _revision(scope.permission_revision),
            "input_revision": _revision(scope.input_revision),
            "operation_id": operation_id,
            "operation_digest": operation_digest,
            "checkpoint_ref": checkpoint_ref,
            "accepted_receipt": receipt,
        }
        identity_digest = _document_digest(core)
        digest = _document_digest({"wait": core, "initial_result_ref": result_ref})
        stable_wait_id = (
            _identity(wait_id, "wait_id") if wait_id else "wait-" + identity_digest[:48]
        )
        try:
            with self.engine.begin() as connection:
                existing = connection.execute(
                    select(waits).where(waits.c.wait_id == stable_wait_id).with_for_update()
                ).mappings().first()
                if existing is not None:
                    if existing["wait_digest"] != digest:
                        raise ContinuationConflict("wait identity was reused with different inputs")
                    return _public_wait(existing, should_enqueue=False)

                self.admission.check_current(scope, "await_operation", connection=connection)
                self._ensure_waiting_source(
                    connection,
                    scope,
                    operation_id=operation_id,
                    operation_digest=operation_digest,
                    checkpoint_ref=checkpoint_ref,
                )
                state = "ready" if result_ref is not None else "waiting"
                connection.execute(
                    insert(waits).values(
                        wait_id=stable_wait_id,
                        wait_digest=digest,
                        task_id=core["task_id"],
                        session_id=core["session_id"],
                        original_run_id=core["original_run_id"],
                        control_revision=core["control_revision"],
                        permission_revision=core["permission_revision"],
                        input_revision=core["input_revision"],
                        operation_id=operation_id,
                        operation_digest=operation_digest,
                        checkpoint_ref=checkpoint_ref,
                        accepted_receipt=receipt,
                        result_ref=result_ref,
                        outcome="waiting_condition",
                        status=state,
                    )
                )
                connection.execute(
                    update(sessions)
                    .where(sessions.c.session_id == core["session_id"])
                    .values(status="waiting", updated_at=func.now())
                )
                authority_update = connection.execute(
                    text(
                        """
                        UPDATE p0_admission.task_authority SET
                            session_status='waiting', run_status='succeeded', updated_at=now()
                        WHERE task_id=:task_id AND session_id=:session_id AND run_id=:run_id
                        """
                    ),
                    {
                        "task_id": core["task_id"],
                        "session_id": core["session_id"],
                        "run_id": core["original_run_id"],
                    },
                )
                if authority_update.rowcount != 1:
                    raise GateDenied("current Run changed while recording its wait")
                self._write_event(
                    connection,
                    stable_wait_id,
                    "agent_run.waiting_condition",
                    digest,
                    {
                        "original_run_id": core["original_run_id"],
                        "operation_id": operation_id,
                        "checkpoint_ref": checkpoint_ref,
                    },
                )
                if result_ref is not None:
                    self._write_event(
                        connection,
                        stable_wait_id,
                        "operation.result_observed",
                        _document_digest(result_ref),
                        result_ref,
                    )
                row = connection.execute(
                    select(waits).where(waits.c.wait_id == stable_wait_id)
                ).mappings().one()
                return _public_wait(row, should_enqueue=False)
        except AdmissionError:
            raise
        except ContinuationError:
            raise
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "wait transaction failed; database details are suppressed"
            ) from None

    def observe_result(
        self, wait_id: str, gateway_result_ref: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Attach a Gateway-queried final-result reference without reopening a Run."""
        wait_id = _identity(wait_id, "wait_id")
        try:
            with self.engine.begin() as connection:
                wait = connection.execute(
                    select(waits).where(waits.c.wait_id == wait_id).with_for_update()
                ).mappings().first()
                if wait is None:
                    raise WaitNotFound()
                result_ref = _json_safe(
                    _result_ref(gateway_result_ref, wait["operation_id"])
                )
                assert result_ref is not None
                if wait["result_ref"] is not None:
                    if wait["result_ref"] != result_ref:
                        raise ContinuationConflict("wait already references a different Gateway result")
                    return _public_wait(wait, should_enqueue=False)
                if wait["status"] != "waiting":
                    raise ContinuationConflict("only an unresolved wait can accept a result reference")
                connection.execute(
                    update(waits)
                    .where(waits.c.wait_id == wait_id, waits.c.status == "waiting")
                    .values(result_ref=result_ref, status="ready", updated_at=func.now())
                )
                self._write_event(
                    connection,
                    wait_id,
                    "operation.result_observed",
                    _document_digest(result_ref),
                    result_ref,
                )
                updated = connection.execute(
                    select(waits).where(waits.c.wait_id == wait_id)
                ).mappings().one()
                return _public_wait(updated, should_enqueue=False)
        except ContinuationError:
            raise
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "result reference could not be attached; database details are suppressed"
            ) from None

    def resume_wait(
        self,
        scope: ExecutionScope,
        wait_id: str,
        *,
        fail_at: str | None = None,
    ) -> dict[str, Any]:
        """Consume a ready wait once and atomically bind/enqueue one new Run."""
        wait_id = _identity(wait_id, "wait_id")
        try:
            with self.engine.begin() as connection:
                wait = connection.execute(
                    select(waits).where(waits.c.wait_id == wait_id).with_for_update()
                ).mappings().first()
                if wait is None:
                    raise WaitNotFound()
                if wait["status"] in {"consumed", "acknowledged"}:
                    expected_digest = _resume_digest(wait)
                    if wait["resume_digest"] != expected_digest:
                        raise ContinuationConflict("resume identity was reused with different facts")
                    return _public_resume(wait, should_enqueue=False)
                if wait["status"] != "ready" or wait["result_ref"] is None:
                    raise WaitPending()

                authority = self._lock_resume_authority(connection, scope, wait)
                session = connection.execute(
                    select(sessions)
                    .where(sessions.c.session_id == wait["session_id"])
                    .with_for_update()
                ).mappings().first()
                if (
                    session is None
                    or session["status"] != "waiting"
                    or session["current_run_id"] != wait["original_run_id"]
                ):
                    raise GateDenied("Session is no longer waiting on this Run")

                resume_digest = _resume_digest(wait)
                new_run_id = _stable_id("run", wait["wait_id"], resume_digest)
                workflow_id = _stable_id("wf", wait["wait_id"], resume_digest)
                payload = {
                    "task_id": wait["task_id"],
                    "session_id": wait["session_id"],
                    "new_run_id": new_run_id,
                    "operation_id": wait["operation_id"],
                    "operation_digest": wait["operation_digest"],
                    "checkpoint_ref": wait["checkpoint_ref"],
                    "result_ref_digest": _document_digest(wait["result_ref"]),
                    "resume_digest": resume_digest,
                }
                payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                connection.execute(
                    insert(runs).values(
                        run_id=new_run_id,
                        task_id=wait["task_id"],
                        session_id=wait["session_id"],
                        status="queued",
                        outcome=None,
                        result_ref={"checkpoint_ref": wait["checkpoint_ref"]},
                    )
                )
                connection.execute(
                    update(sessions)
                    .where(sessions.c.session_id == wait["session_id"])
                    .values(status="running", current_run_id=new_run_id, updated_at=func.now())
                )
                updated_authority = connection.execute(
                    text(
                        """
                        UPDATE p0_admission.task_authority SET
                            run_id=:new_run_id, session_status='running',
                            run_status='queued', updated_at=now()
                        WHERE task_id=:task_id AND session_id=:session_id AND run_id=:old_run_id
                          AND task_status='active' AND cancel_requested=false AND permitted=true
                          AND input_valid=true AND control_revision=:control_revision
                          AND permission_revision=:permission_revision
                          AND input_revision=:input_revision
                        """
                    ),
                    {
                        "new_run_id": new_run_id,
                        "task_id": wait["task_id"],
                        "session_id": wait["session_id"],
                        "old_run_id": wait["original_run_id"],
                        "control_revision": authority["control_revision"],
                        "permission_revision": authority["permission_revision"],
                        "input_revision": authority["input_revision"],
                    },
                )
                if updated_authority.rowcount != 1:
                    raise GateDenied("current Task authority changed during resume")
                connection.execute(
                    update(waits)
                    .where(waits.c.wait_id == wait_id, waits.c.status == "ready")
                    .values(
                        status="consumed",
                        resume_digest=resume_digest,
                        new_run_id=new_run_id,
                        workflow_id=workflow_id,
                        updated_at=func.now(),
                    )
                )
                self._write_event(
                    connection,
                    wait_id,
                    "agent_run.resumed",
                    resume_digest,
                    {
                        "new_run_id": new_run_id,
                        "workflow_id": workflow_id,
                        "operation_id": wait["operation_id"],
                    },
                )
                connection.execute(
                    insert(workflow_bindings).values(
                        workflow_id=workflow_id,
                        wait_id=wait_id,
                        task_id=wait["task_id"],
                        session_id=wait["session_id"],
                        run_id=new_run_id,
                        workflow_name=WORKFLOW_NAME,
                        queue_name=self.queue_name,
                        application_name=self.application_name,
                        code_version=self.code_version,
                        request_digest=resume_digest,
                    )
                )
                self.client.enqueue_in_transaction(
                    connection,
                    _enqueue_options(
                        workflow_id=workflow_id,
                        workflow_name=WORKFLOW_NAME,
                        queue_name=self.queue_name,
                        application_name=self.application_name,
                        code_version=self.code_version,
                    ),
                    payload_json,
                )
                if fail_at == "enqueue":
                    raise InjectedContinuationFailure("enqueue")
                consumed = connection.execute(
                    select(waits).where(waits.c.wait_id == wait_id)
                ).mappings().one()
                return _public_resume(consumed, should_enqueue=True)
        except (AdmissionError, ContinuationError):
            raise
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "resume transaction failed; database details are suppressed"
            ) from None
        except Exception:
            raise ContinuationError(
                "DBOS enqueue or continuation failed; details are suppressed"
            ) from None

    def complete_resume(
        self,
        scope: ExecutionScope,
        wait_id: str,
        workflow_result: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Acknowledge a public DBOS result under the current app-owned Run gate.

        DBOS success is evidence that this bounded reference workflow returned. The
        Task remains active; this command records the Run result as continue_required.
        """
        wait_id = _identity(wait_id, "wait_id")
        if not isinstance(workflow_result, Mapping):
            raise ContinuationConflict("workflow result must be a bounded reference mapping")
        preflight_wait = self.evidence(wait_id)["wait"]
        workflow_id = preflight_wait["workflow_id"]
        if not isinstance(workflow_id, str):
            raise ContinuationConflict("wait has no public DBOS workflow binding")
        provided_refs = _validated_workflow_result(workflow_result, preflight_wait)
        try:
            public_handle = self.client.retrieve_workflow(workflow_id)
            public_status = public_handle.get_status()
            if public_status.status != "SUCCESS":
                raise ContinuationConflict("public DBOS workflow has not succeeded")
            actual_result = public_handle.get_result(polling_interval_sec=0.05)
        except ContinuationError:
            raise
        except Exception:
            raise ContinuationError(
                "public DBOS result could not be verified; details are suppressed"
            ) from None
        actual_refs = _validated_workflow_result(actual_result, preflight_wait)
        if actual_refs != provided_refs:
            raise ContinuationConflict("supplied result differs from the public DBOS result")
        try:
            with self.engine.begin() as connection:
                wait = connection.execute(
                    select(waits).where(waits.c.wait_id == wait_id).with_for_update()
                ).mappings().first()
                if wait is None:
                    raise WaitNotFound()
                result_refs = _validated_workflow_result(workflow_result, wait)
                result_digest = _document_digest(result_refs)
                binding = connection.execute(
                    select(workflow_bindings)
                    .where(workflow_bindings.c.wait_id == wait_id)
                    .with_for_update()
                ).mappings().first()
                if (
                    wait["new_run_id"] != result_refs["new_run_id"]
                    or wait["workflow_id"] is None
                    or binding is None
                    or binding["workflow_id"] != wait["workflow_id"]
                    or binding["run_id"] != wait["new_run_id"]
                    or binding["request_digest"] != wait["resume_digest"]
                ):
                    raise ContinuationConflict("public result does not match the saved workflow binding")
                event_id = _stable_id("evt", wait_id, "agent_run.succeeded", result_digest)
                if wait["status"] == "acknowledged":
                    event = connection.execute(
                        select(events).where(events.c.event_id == event_id)
                    ).mappings().first()
                    if event is None or event["event_digest"] != result_digest:
                        raise ContinuationConflict("acknowledged Run result does not match the replay")
                    if (
                        _scope_identity(scope, "task_id") != wait["task_id"]
                        or _scope_identity(scope, "session_id") != wait["session_id"]
                        or _scope_identity(scope, "run_id") != wait["new_run_id"]
                    ):
                        raise ContinuationConflict("acknowledgment replay refers to another Run")
                    return _public_ack(wait, applied=False)
                if wait["status"] != "consumed":
                    raise WaitPending()

                authority = self._lock_completion_authority(connection, scope, wait)
                session = connection.execute(
                    select(sessions)
                    .where(sessions.c.session_id == wait["session_id"])
                    .with_for_update()
                ).mappings().first()
                if (
                    session is None
                    or session["task_id"] != wait["task_id"]
                    or session["status"] != "running"
                    or session["current_run_id"] != wait["new_run_id"]
                ):
                    raise GateDenied("Session is no longer running the bound continuation Run")
                run = connection.execute(
                    select(runs).where(runs.c.run_id == wait["new_run_id"]).with_for_update()
                ).mappings().first()
                if (
                    run is None
                    or run["task_id"] != wait["task_id"]
                    or run["session_id"] != wait["session_id"]
                    or run["status"] not in {"queued", "running"}
                    or run["outcome"] is not None
                ):
                    raise ContinuationConflict("new Run already has a different application result")

                run_update = connection.execute(
                    update(runs)
                    .where(
                        runs.c.run_id == wait["new_run_id"],
                        runs.c.status.in_(("queued", "running")),
                        runs.c.outcome.is_(None),
                    )
                    .values(
                        status="succeeded",
                        outcome="continue_required",
                        result_ref=result_refs,
                    )
                )
                session_update = connection.execute(
                    update(sessions)
                    .where(
                        sessions.c.session_id == wait["session_id"],
                        sessions.c.status == "running",
                        sessions.c.current_run_id == wait["new_run_id"],
                    )
                    .values(status="idle", updated_at=func.now())
                )
                authority_update = connection.execute(
                    text(
                        """
                        UPDATE p0_admission.task_authority SET
                            session_status='idle', run_status='succeeded', updated_at=now()
                        WHERE task_id=:task_id AND session_id=:session_id AND run_id=:run_id
                          AND task_status='active' AND cancel_requested=false AND permitted=true
                          AND input_valid=true AND control_revision=:control_revision
                          AND permission_revision=:permission_revision
                          AND input_revision=:input_revision
                          AND session_status='running' AND run_status IN ('queued','running')
                        """
                    ),
                    {
                        "task_id": wait["task_id"],
                        "session_id": wait["session_id"],
                        "run_id": wait["new_run_id"],
                        "control_revision": authority["control_revision"],
                        "permission_revision": authority["permission_revision"],
                        "input_revision": authority["input_revision"],
                    },
                )
                wait_update = connection.execute(
                    update(waits)
                    .where(waits.c.wait_id == wait_id, waits.c.status == "consumed")
                    .values(status="acknowledged", updated_at=func.now())
                )
                if any(
                    result.rowcount != 1
                    for result in (run_update, session_update, authority_update, wait_update)
                ):
                    raise GateDenied("current Task, Session, Run, or Wait changed during acknowledgment")
                self._write_event(
                    connection,
                    wait_id,
                    "agent_run.succeeded",
                    result_digest,
                    {
                        "new_run_id": wait["new_run_id"],
                        "workflow_id": wait["workflow_id"],
                        "outcome": "continue_required",
                        "workflow_result_digest": result_digest,
                    },
                )
                return _public_ack(
                    {**wait, "status": "acknowledged"}, applied=True
                )
        except (AdmissionError, ContinuationError):
            raise
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "workflow result acknowledgment failed; database details are suppressed"
            ) from None

    def evidence(self, wait_id: str) -> dict[str, Any]:
        """Read a bounded wait/session/Run/event/binding summary for the probe."""
        wait_id = _identity(wait_id, "wait_id")
        try:
            with self.engine.connect() as connection:
                wait = connection.execute(
                    select(waits).where(waits.c.wait_id == wait_id)
                ).mappings().first()
                if wait is None:
                    raise WaitNotFound()
                session = connection.execute(
                    select(sessions).where(sessions.c.session_id == wait["session_id"])
                ).mappings().one()
                run_rows = connection.execute(
                    select(runs.c.run_id, runs.c.status, runs.c.outcome)
                    .where(runs.c.session_id == wait["session_id"])
                    .order_by(runs.c.created_at)
                ).mappings().all()
                event_count = connection.execute(
                    select(func.count()).select_from(events).where(events.c.wait_id == wait_id)
                ).scalar_one()
                binding = connection.execute(
                    select(workflow_bindings).where(workflow_bindings.c.wait_id == wait_id)
                ).mappings().first()
                return {
                    "wait": _public_wait(wait, should_enqueue=False),
                    "session_status": session["status"],
                    "current_run_id": session["current_run_id"],
                    "runs": [
                        {"run_id": item["run_id"], "status": item["status"], "outcome": item["outcome"]}
                        for item in run_rows
                    ],
                    "event_count": int(event_count),
                    "workflow_binding": _public_binding(binding) if binding else None,
                }
        except ContinuationError:
            raise
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "continuation evidence lookup failed; database details are suppressed"
            ) from None

    def _ensure_waiting_source(
        self,
        connection: Connection,
        scope: ExecutionScope,
        *,
        operation_id: str,
        operation_digest: str,
        checkpoint_ref: str,
    ) -> None:
        task_id = _scope_identity(scope, "task_id")
        session_id = _scope_identity(scope, "session_id")
        run_id = _scope_identity(scope, "run_id")
        session = connection.execute(
            select(sessions).where(sessions.c.session_id == session_id).with_for_update()
        ).mappings().first()
        if session is None:
            connection.execute(
                insert(sessions).values(
                    session_id=session_id,
                    task_id=task_id,
                    status="running",
                    current_run_id=run_id,
                )
            )
        elif (
            session["task_id"] != task_id
            or session["status"] != "running"
            or session["current_run_id"] != run_id
        ):
            raise GateDenied("Session is not running the supplied current Run")
        run_ref = {
            "operation_id": operation_id,
            "operation_digest": operation_digest,
            "checkpoint_ref": checkpoint_ref,
        }
        run = connection.execute(
            select(runs).where(runs.c.run_id == run_id).with_for_update()
        ).mappings().first()
        if run is None:
            connection.execute(
                insert(runs).values(
                    run_id=run_id,
                    task_id=task_id,
                    session_id=session_id,
                    status="succeeded",
                    outcome="waiting_condition",
                    result_ref=run_ref,
                )
            )
        elif run["task_id"] != task_id or run["session_id"] != session_id:
            raise ContinuationConflict("Run identity is already bound to another scope")
        elif (run["status"], run["outcome"]) == ("succeeded", "waiting_condition"):
            if run["result_ref"] != run_ref:
                raise ContinuationConflict("original Run result cannot be overwritten")
        elif (run["status"], run["outcome"]) != ("succeeded", "waiting_condition"):
            if run["status"] != "running" or run["outcome"] is not None:
                raise ContinuationConflict("original Run already has a different result")
            connection.execute(
                update(runs)
                .where(runs.c.run_id == run_id, runs.c.status == "running")
                .values(status="succeeded", outcome="waiting_condition", result_ref=run_ref)
            )

    def _write_event(
        self,
        connection: Connection,
        wait_id: str,
        event_type: str,
        digest: str,
        refs: Mapping[str, Any],
    ) -> None:
        event_id = _stable_id("evt", wait_id, event_type, digest)
        connection.execute(
            insert(events).values(
                event_id=event_id,
                wait_id=wait_id,
                event_type=event_type,
                event_digest=digest,
                event_refs=dict(refs),
            )
        )

    def _lock_resume_authority(
        self,
        connection: Connection,
        scope: ExecutionScope,
        wait: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        row = connection.execute(
            text("SELECT * FROM p0_admission.task_authority WHERE task_id=:task_id FOR UPDATE"),
            {"task_id": wait["task_id"]},
        ).mappings().first()
        if row is None:
            raise GateDenied("current Task authority is unavailable")
        expected = {
            "task_id": _scope_identity(scope, "task_id"),
            "session_id": _scope_identity(scope, "session_id"),
            "run_id": _scope_identity(scope, "run_id"),
            "control_revision": _revision(scope.control_revision),
            "permission_revision": _revision(scope.permission_revision),
            "input_revision": _revision(scope.input_revision),
        }
        if any(row[key] != value for key, value in expected.items()):
            raise GateDenied("Task, Run, permission, control, or input revision is stale")
        if row["task_status"] != "active" or row["cancel_requested"] or not row["permitted"]:
            raise GateDenied("current Task status, cancellation, or permission denies resume")
        if not row["input_valid"]:
            raise GateDenied("current input revision is invalid")
        if row["session_status"] != "waiting" or row["run_status"] != "succeeded":
            raise GateDenied("Task is not waiting on a completed Run")
        if (
            wait["task_id"] != expected["task_id"]
            or wait["session_id"] != expected["session_id"]
            or wait["original_run_id"] != expected["run_id"]
        ):
            raise GateDenied("wait does not belong to the supplied current Run")
        if any(
            wait[field] != expected[field]
            for field in ("control_revision", "permission_revision", "input_revision")
        ):
            raise GateDenied("wait was created under different authority revisions")
        return row

    def _lock_completion_authority(
        self,
        connection: Connection,
        scope: ExecutionScope,
        wait: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        row = connection.execute(
            text("SELECT * FROM p0_admission.task_authority WHERE task_id=:task_id FOR UPDATE"),
            {"task_id": wait["task_id"]},
        ).mappings().first()
        if row is None:
            raise GateDenied("current Task authority is unavailable")
        expected = {
            "task_id": _scope_identity(scope, "task_id"),
            "session_id": _scope_identity(scope, "session_id"),
            "run_id": _scope_identity(scope, "run_id"),
            "control_revision": _revision(scope.control_revision),
            "permission_revision": _revision(scope.permission_revision),
            "input_revision": _revision(scope.input_revision),
        }
        if any(row[key] != value for key, value in expected.items()):
            raise GateDenied("current Task, Run, or authority revision is stale")
        if (
            row["task_status"] != "active"
            or row["cancel_requested"]
            or not row["permitted"]
            or not row["input_valid"]
        ):
            raise GateDenied("current Task, cancellation, permission, or input gate denies acknowledgment")
        if row["session_status"] != "running" or row["run_status"] not in {"queued", "running"}:
            raise GateDenied("current Session/Run is not eligible for result acknowledgment")
        if (
            wait["task_id"] != expected["task_id"]
            or wait["session_id"] != expected["session_id"]
            or wait["new_run_id"] != expected["run_id"]
        ):
            raise GateDenied("wait is not bound to the supplied current Run")
        if any(
            wait[field] != expected[field]
            for field in ("control_revision", "permission_revision", "input_revision")
        ):
            raise GateDenied("wait was created under different authority revisions")
        return row


def _enqueue_options(
    *,
    workflow_id: str,
    workflow_name: str,
    queue_name: str,
    application_name: str,
    code_version: str,
) -> EnqueueOptions:
    return {
        "workflow_name": workflow_name,
        "queue_name": queue_name,
        "workflow_id": workflow_id,
        "workflow_id_reuse_policy": "return-existing",
        "app_version": code_version,
        "application_name": application_name,
    }


def _accepted_receipt(
    receipt: Mapping[str, Any], operation_id: str, operation_digest: str
) -> dict[str, str]:
    if not isinstance(receipt, Mapping):
        raise ContinuationError("accepted receipt must be a mapping")
    if receipt.get("status") != "accepted":
        raise ContinuationError("only an accepted receipt can create a wait")
    if _identity(receipt.get("operation_id"), "receipt.operation_id") != operation_id:
        raise ContinuationConflict("receipt operation identity does not match the wait")
    if _digest(receipt.get("request_digest")) != operation_digest:
        raise ContinuationConflict("receipt digest does not match the wait")
    tool_call_id = _identity(receipt.get("accepted_tool_call_id"), "accepted_tool_call_id")
    return {
        "status": "accepted",
        "operation_id": operation_id,
        "request_digest": operation_digest,
        "accepted_tool_call_id": tool_call_id,
    }


def _result_ref(value: Mapping[str, Any] | None, operation_id: str) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ContinuationError("Gateway result reference must be a mapping")
    if value.get("schema") != "p0_protocol.operations":
        raise ContinuationConflict("result reference must point to the Gateway operation ledger")
    normalized = {
        "schema": "p0_protocol.operations",
        "probe_id": _identity(value.get("probe_id"), "result_ref.probe_id"),
        "operation_id": _identity(value.get("operation_id"), "result_ref.operation_id"),
        "result_id": _identity(value.get("result_id"), "result_ref.result_id"),
        "result_digest": _digest(value.get("result_digest")),
    }
    if normalized["operation_id"] != operation_id:
        raise ContinuationConflict("Gateway result reference belongs to another operation")
    return normalized


def _scope_identity(scope: ExecutionScope, field: str) -> str:
    value = getattr(scope, field, None)
    return _identity(value, f"scope.{field}")


def _revision(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ContinuationError("scope revision must be a string or integer")
    normalized = str(value).strip()
    if not normalized or len(normalized) > 160:
        raise ContinuationError("scope revision is invalid")
    return normalized


def _identity(value: object, field: str, maximum: int = 240) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ContinuationError(f"{field} must be a bounded non-empty identifier")
    return value.strip()


def _digest(value: object) -> str:
    if not isinstance(value, str) or not _HEX_DIGEST.fullmatch(value):
        raise ContinuationError("digest must be a SHA-256 hex value")
    return value.removeprefix("sha256:").lower()


def _document_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-" + hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:48]


def _resume_digest(wait: Mapping[str, Any]) -> str:
    return _document_digest(
        {
            "wait_id": wait["wait_id"],
            "wait_digest": wait["wait_digest"],
            "result_ref": wait["result_ref"],
        }
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if value is None or type(value) in {str, int, float, bool}:
        return value
    raise ContinuationError("reference data contains an unsupported value")


def _public_wait(row: Mapping[str, Any], *, should_enqueue: bool) -> dict[str, Any]:
    return {
        "wait_id": row["wait_id"],
        "wait_digest": row["wait_digest"],
        "task_id": row["task_id"],
        "session_id": row["session_id"],
        "original_run_id": row["original_run_id"],
        "operation_id": row["operation_id"],
        "operation_digest": row["operation_digest"],
        "checkpoint_ref": row["checkpoint_ref"],
        "accepted_receipt": row["accepted_receipt"],
        "result_ref": row["result_ref"],
        "outcome": row["outcome"],
        "status": row["status"],
        "resume_digest": row["resume_digest"],
        "new_run_id": row["new_run_id"],
        "workflow_id": row["workflow_id"],
        "should_enqueue": should_enqueue,
    }


def _public_resume(row: Mapping[str, Any], *, should_enqueue: bool) -> dict[str, Any]:
    return {
        "wait_id": row["wait_id"],
        "new_run_id": row["new_run_id"],
        "workflow_id": row["workflow_id"],
        "resume_digest": row["resume_digest"],
        "should_enqueue": should_enqueue,
    }


def _public_ack(row: Mapping[str, Any], *, applied: bool) -> dict[str, Any]:
    return {
        "wait_id": row["wait_id"],
        "new_run_id": row["new_run_id"],
        "workflow_id": row["workflow_id"],
        "run_status": "succeeded",
        "run_outcome": "continue_required",
        "session_status": "idle",
        "task_status": "active",
        "applied": applied,
    }


def _public_binding(row: Mapping[str, Any]) -> dict[str, str]:
    return {
        "workflow_id": row["workflow_id"],
        "wait_id": row["wait_id"],
        "task_id": row["task_id"],
        "session_id": row["session_id"],
        "run_id": row["run_id"],
        "workflow_name": row["workflow_name"],
        "queue_name": row["queue_name"],
        "application_name": row["application_name"],
        "code_version": row["code_version"],
        "request_digest": row["request_digest"],
    }
