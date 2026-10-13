"""Isolated P0 Task/Run admission and model-request cost ledger.

This adapter owns only the ``p0_admission`` schema. Callers pass an existing
SQLAlchemy Engine so admission can share its PostgreSQL transaction with later
checkpoint and Gateway adapters.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from integrations.model_pricing import (
    PRICE_REVISION,
    PricingInputError,
    calculate_official_usage_cost,
    calculate_reservation_upper_bound,
)

SCHEMA = "p0_admission"
MODEL = "gpt-6-luna"
PRICE_SERVICE_TIER = "standard"
PROCESSING_MODE = "global"
OTHER_CHARGES_BASIS = "custom function tools only; no billed OpenAI hosted tools"
_REVISION_FIELDS = ("control_revision", "permission_revision", "input_revision")
_SCOPE_FIELDS = (
    "task_id",
    "session_id",
    "run_id",
    "control_revision",
    "permission_revision",
    "input_revision",
)
_TASK_STATUSES = frozenset(
    {"draft", "active", "paused", "waiting_input", "completed", "failed", "cancelled"}
)
_SESSION_STATUSES = frozenset(
    {"idle", "queued", "running", "waiting", "paused", "completed", "failed"}
)
_RUN_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "interrupted"})
_DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-fA-F]{64}$")
_EVIDENCE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}$")


class AdmissionError(RuntimeError):
    """Base class for safe, caller-facing admission failures."""


class GateDenied(AdmissionError):
    """The current Task, Session, Run, permission, or input gate denied an action."""


class IdempotencyConflict(AdmissionError):
    """A stable request identity was reused with a different digest."""


class ResultConflict(AdmissionError):
    """A request was given a different final usage result."""


class ReconciliationConflict(AdmissionError):
    """A factual reconciliation conflicts with the saved unknown or evidence."""


class BudgetExceeded(AdmissionError):
    """The request's conservative cost bound exceeds the remaining Task budget."""


class ScopeConflict(AdmissionError):
    """The supplied scope is stale or conflicts with the current Task row."""


class AdmissionInputError(AdmissionError):
    """An input cannot be stored or priced safely."""


class AdmissionStorageError(AdmissionError):
    """Storage failed; database details are intentionally suppressed."""


@dataclass(frozen=True, slots=True)
class ExecutionScope:
    task_id: str
    session_id: str
    run_id: str
    control_revision: str | int
    permission_revision: str | int
    input_revision: str | int


class SeamAdmission:
    """Current-scope gate and idempotent, per-request model-cost reservation."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def bootstrap(self) -> None:
        """Create only the dedicated admission schema and its two tables."""
        ddl = (
            "CREATE SCHEMA IF NOT EXISTS p0_admission",
            """
            CREATE TABLE IF NOT EXISTS p0_admission.task_authority (
                task_id text PRIMARY KEY,
                session_id text NOT NULL UNIQUE,
                run_id text NOT NULL UNIQUE,
                task_status text NOT NULL CHECK (task_status IN
                    ('draft','active','paused','waiting_input','completed','failed','cancelled')),
                session_status text NOT NULL CHECK (session_status IN
                    ('idle','queued','running','waiting','paused','completed','failed')),
                run_status text NOT NULL CHECK (run_status IN
                    ('queued','running','succeeded','failed','interrupted')),
                cancel_requested boolean NOT NULL,
                control_revision text NOT NULL,
                permission_revision text NOT NULL,
                input_revision text NOT NULL,
                input_valid boolean NOT NULL,
                permitted boolean NOT NULL,
                budget_usd numeric NOT NULL CHECK (budget_usd >= 0),
                reservation_bound_exceeded boolean NOT NULL DEFAULT false,
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS p0_admission.model_requests (
                request_id text PRIMARY KEY,
                request_digest text NOT NULL,
                task_id text NOT NULL REFERENCES p0_admission.task_authority(task_id),
                session_id text NOT NULL,
                run_id text NOT NULL,
                control_revision text NOT NULL,
                permission_revision text NOT NULL,
                input_revision text NOT NULL,
                model text NOT NULL,
                price_revision text NOT NULL,
                supplier_service_tier text NOT NULL,
                status text NOT NULL CHECK (status IN ('reserved','unknown','settled')),
                input_tokens_upper_bound integer NOT NULL CHECK (input_tokens_upper_bound >= 0),
                max_output_tokens integer NOT NULL CHECK (max_output_tokens >= 0),
                reservation_usd numeric NOT NULL CHECK (reservation_usd >= 0),
                reservation_details jsonb NOT NULL,
                usage jsonb,
                cost_details jsonb,
                actual_cost_usd numeric,
                supplier_invoice_amount_usd numeric,
                http_status integer,
                result_digest text,
                reservation_bound_exceeded boolean NOT NULL DEFAULT false,
                reconciliation_evidence_ref text,
                reconciliation_digest text,
                reconciliation_history jsonb NOT NULL DEFAULT '[]'::jsonb,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            )
            """,
            "CREATE INDEX IF NOT EXISTS model_requests_task_status_idx "
            "ON p0_admission.model_requests (task_id, status)",
            "ALTER TABLE p0_admission.task_authority "
            "ADD COLUMN IF NOT EXISTS reservation_bound_exceeded boolean NOT NULL DEFAULT false",
            "ALTER TABLE p0_admission.model_requests "
            "ADD COLUMN IF NOT EXISTS reservation_bound_exceeded boolean NOT NULL DEFAULT false",
            "ALTER TABLE p0_admission.model_requests "
            "ADD COLUMN IF NOT EXISTS reconciliation_evidence_ref text",
            "ALTER TABLE p0_admission.model_requests "
            "ADD COLUMN IF NOT EXISTS reconciliation_digest text",
            "ALTER TABLE p0_admission.model_requests "
            "ADD COLUMN IF NOT EXISTS reconciliation_history jsonb NOT NULL DEFAULT '[]'::jsonb",
        )
        try:
            with self.engine.begin() as connection:
                for statement in ddl:
                    connection.execute(text(statement))
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "could not bootstrap the isolated admission schema; database details are suppressed"
            ) from None

    def seed_scope(self, scope: ExecutionScope, budget_usd: Decimal) -> None:
        """Create one isolated current Task/Session/Run fixture and its budget."""
        budget = _money(budget_usd, "budget_usd")
        values = _scope_values(scope)
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO p0_admission.task_authority (
                            task_id, session_id, run_id, task_status, session_status,
                            run_status, cancel_requested, control_revision,
                            permission_revision, input_revision, input_valid, permitted,
                            budget_usd
                        ) VALUES (
                            :task_id, :session_id, :run_id, 'active', 'running',
                            'running', false, :control_revision, :permission_revision,
                            :input_revision, true, true, :budget_usd
                        )
                        """
                    ),
                    {**values, "budget_usd": budget},
                )
        except SQLAlchemyError:
            raise ScopeConflict(
                "scope could not be seeded; use a unique Task, Session, and Run identity"
            ) from None

    def locked_current(
        self, connection: Connection, scope: ExecutionScope, action: str
    ) -> dict[str, Any]:
        """Validate and row-lock current authority inside the caller's transaction."""
        _require_transaction(connection)
        try:
            row = self._locked_authority(connection, scope, action)
            return _public_gate(row)
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "current admission lookup failed; database details are suppressed"
            ) from None

    def check_current(
        self,
        scope: ExecutionScope,
        action: str,
        connection: Connection | None = None,
    ) -> dict[str, Any]:
        """Check current authority, optionally joining a caller-owned transaction.

        Pass an active SQLAlchemy Connection to keep this row lock and any following
        Gateway or checkpoint write in the same PostgreSQL transaction.
        """
        if connection is not None:
            return self.locked_current(connection, scope, action)
        try:
            with self.engine.begin() as own_connection:
                row = self._locked_authority(own_connection, scope, action)
                return _public_gate(row)
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "current admission lookup failed; database details are suppressed"
            ) from None

    def reserve_request(
        self,
        scope: ExecutionScope,
        request_id: str,
        request_digest: str,
        input_tokens_upper_bound: int,
        max_output_tokens: int,
    ) -> dict[str, Any]:
        """Recheck authority and atomically reserve the official conservative bound."""
        request_id = _identity(request_id, "request_id")
        digest = _digest(request_digest)
        input_bound = _token_count(input_tokens_upper_bound, "input_tokens_upper_bound")
        output_bound = _token_count(max_output_tokens, "max_output_tokens")
        try:
            details = calculate_reservation_upper_bound(
                model=MODEL,
                service_tier=PRICE_SERVICE_TIER,
                processing_mode=PROCESSING_MODE,
                input_tokens_upper_bound=input_bound,
                max_output_tokens=output_bound,
                other_charges_upper_bound_usd=Decimal("0"),
                other_charges_basis=OTHER_CHARGES_BASIS,
            )
        except PricingInputError:
            raise AdmissionInputError(
                "request token bounds are outside the frozen pricing snapshot"
            ) from None
        reservation = details["reservation_upper_bound_usd"]
        assert isinstance(reservation, Decimal)
        safe_details = _json_safe(details)
        values = _scope_values(scope)
        try:
            with self.engine.begin() as connection:
                existing = connection.execute(
                    text("SELECT * FROM p0_admission.model_requests WHERE request_id=:request_id"),
                    {"request_id": request_id},
                ).mappings().first()
                if existing is not None:
                    return _existing_reservation(existing, values, digest)

                authority = self._locked_authority(connection, scope, "model_request")
                # The Task lock serializes fresh reservations for the same scope.
                existing = connection.execute(
                    text("SELECT * FROM p0_admission.model_requests WHERE request_id=:request_id"),
                    {"request_id": request_id},
                ).mappings().first()
                if existing is not None:
                    return _existing_reservation(existing, values, digest)

                occupied = connection.execute(
                    text(
                        """
                        SELECT COALESCE(SUM(
                            CASE WHEN status='settled' THEN actual_cost_usd
                                 ELSE reservation_usd END
                        ), 0) AS occupied_usd
                        FROM p0_admission.model_requests WHERE task_id=:task_id
                        """
                    ),
                    {"task_id": scope.task_id},
                ).scalar_one()
                available = authority["budget_usd"] - occupied
                if reservation > available:
                    raise BudgetExceeded("request reservation exceeds the remaining Task budget")

                inserted = connection.execute(
                    text(
                        """
                        INSERT INTO p0_admission.model_requests (
                            request_id, request_digest, task_id, session_id, run_id,
                            control_revision, permission_revision, input_revision,
                            model, price_revision, supplier_service_tier, status,
                            input_tokens_upper_bound, max_output_tokens, reservation_usd,
                            reservation_details
                        ) VALUES (
                            :request_id, :request_digest, :task_id, :session_id, :run_id,
                            :control_revision, :permission_revision, :input_revision,
                            :model, :price_revision, :supplier_service_tier, 'reserved',
                            :input_tokens_upper_bound, :max_output_tokens, :reservation_usd,
                            CAST(:reservation_details AS jsonb)
                        ) RETURNING *
                        """
                    ),
                    {
                        **values,
                        "request_id": request_id,
                        "request_digest": digest,
                        "model": MODEL,
                        "price_revision": PRICE_REVISION,
                        "supplier_service_tier": "default",
                        "input_tokens_upper_bound": input_bound,
                        "max_output_tokens": output_bound,
                        "reservation_usd": reservation,
                        "reservation_details": json.dumps(safe_details, separators=(",", ":")),
                    },
                ).mappings().one()
                return _public_request(inserted, should_send=True)
        except AdmissionError:
            raise
        except IntegrityError:
            existing = self.query_request(request_id)
            if existing is not None:
                return _existing_reservation(existing, values, digest)
            raise ScopeConflict("request identity conflicted with a concurrent reservation") from None
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "request reservation failed; database details are suppressed"
            ) from None

    def record_result(
        self,
        request_id: str,
        usage: Mapping[str, object] | None,
        service_tier: str = "default",
        http_status: int | None = None,
    ) -> dict[str, Any]:
        """Persist safe supplier usage; incomplete evidence keeps the full hold unknown."""
        request_id = _identity(request_id, "request_id")
        supplier_tier, priced_tier = _service_tiers(service_tier)
        status_code = _http_status(http_status)
        safe_usage = _normalise_usage(usage)
        result_digest = _result_digest(safe_usage, supplier_tier, status_code)
        try:
            with self.engine.begin() as connection:
                request = connection.execute(
                    text("SELECT * FROM p0_admission.model_requests WHERE request_id=:request_id"),
                    {"request_id": request_id},
                ).mappings().first()
                if request is None:
                    raise AdmissionInputError("unknown model request identity")
                authority = connection.execute(
                    text("SELECT task_id FROM p0_admission.task_authority "
                         "WHERE task_id=:task_id FOR UPDATE"),
                    {"task_id": request["task_id"]},
                ).mappings().first()
                if authority is None:
                    raise AdmissionStorageError("request authority row is missing")
                request = connection.execute(
                    text("SELECT * FROM p0_admission.model_requests WHERE request_id=:request_id FOR UPDATE"),
                    {"request_id": request_id},
                ).mappings().one()
                if request["result_digest"] is not None:
                    if request["result_digest"] != result_digest:
                        raise ResultConflict("request identity already has a different result")
                    return _public_request(request, should_send=False)

                if priced_tier is None:
                    cost = _unknown_cost_details(safe_usage, supplier_tier)
                else:
                    cost = calculate_official_usage_cost(
                        safe_usage,
                        model=MODEL,
                        service_tier=priced_tier,
                        processing_mode=PROCESSING_MODE,
                        other_charges_usd=Decimal("0"),
                        other_charges_basis=OTHER_CHARGES_BASIS,
                    )
                actual_cost = cost["official_estimated_total_usd"]
                state = "settled" if isinstance(actual_cost, Decimal) else "unknown"
                bound_exceeded = _usage_exceeds_reservation(request, safe_usage)
                connection.execute(
                    text(
                        """
                        UPDATE p0_admission.model_requests SET
                            supplier_service_tier=:supplier_service_tier,
                            status=:status,
                            usage=CAST(:usage AS jsonb),
                            cost_details=CAST(:cost_details AS jsonb),
                            actual_cost_usd=:actual_cost_usd,
                            supplier_invoice_amount_usd=NULL,
                            http_status=:http_status,
                            result_digest=:result_digest,
                            reservation_bound_exceeded=:reservation_bound_exceeded,
                            updated_at=now()
                        WHERE request_id=:request_id
                        """
                    ),
                    {
                        "supplier_service_tier": supplier_tier,
                        "status": state,
                        "usage": (
                            json.dumps(safe_usage, separators=(",", ":"))
                            if safe_usage is not None
                            else "null"
                        ),
                        "cost_details": json.dumps(_json_safe(cost), separators=(",", ":")),
                        "actual_cost_usd": actual_cost,
                        "http_status": status_code,
                        "result_digest": result_digest,
                        "reservation_bound_exceeded": bound_exceeded,
                        "request_id": request_id,
                    },
                )
                if bound_exceeded:
                    connection.execute(
                        text(
                            "UPDATE p0_admission.task_authority "
                            "SET reservation_bound_exceeded=true, updated_at=now() "
                            "WHERE task_id=:task_id"
                        ),
                        {"task_id": request["task_id"]},
                    )
                updated = connection.execute(
                    text("SELECT * FROM p0_admission.model_requests WHERE request_id=:request_id"),
                    {"request_id": request_id},
                ).mappings().one()
                return _public_request(updated, should_send=False)
        except AdmissionError:
            raise
        except (PricingInputError, SQLAlchemyError):
            raise AdmissionStorageError(
                "request result could not be recorded; details are suppressed"
            ) from None

    def reconcile_result(
        self,
        current_scope: ExecutionScope,
        request_id: str,
        usage: Mapping[str, object] | None,
        provider_evidence_ref: str,
        service_tier: str = "default",
        http_status: int | None = None,
    ) -> dict[str, Any]:
        """Replace only an unknown ledger projection using referenced provider facts.

        This is factual reconciliation, not ordinary Task progress: it remains
        available after cancellation or Run completion when current permission and
        scope revisions still match. It never starts a request.
        """
        request_id = _identity(request_id, "request_id")
        evidence_ref = _provider_evidence_ref(provider_evidence_ref)
        supplier_tier, priced_tier = _service_tiers(service_tier)
        status_code = _http_status(http_status)
        safe_usage = _normalise_usage(usage)
        reconciliation_digest = _reconciliation_digest(
            evidence_ref, safe_usage, supplier_tier, status_code
        )
        try:
            with self.engine.begin() as connection:
                authority = connection.execute(
                    text(
                        "SELECT * FROM p0_admission.task_authority "
                        "WHERE task_id=:task_id FOR UPDATE"
                    ),
                    {"task_id": _scope_values(current_scope)["task_id"]},
                ).mappings().first()
                if authority is None:
                    raise GateDenied("current Task authority is unavailable")
                _validate_reconciliation_scope(authority, current_scope)
                request = connection.execute(
                    text(
                        "SELECT * FROM p0_admission.model_requests "
                        "WHERE request_id=:request_id FOR UPDATE"
                    ),
                    {"request_id": request_id},
                ).mappings().first()
                if request is None:
                    raise AdmissionInputError("unknown model request identity")
                if (
                    request["task_id"] != authority["task_id"]
                    or request["session_id"] != authority["session_id"]
                ):
                    raise ScopeConflict("request does not belong to the current Task Session")
                if request["reconciliation_digest"] is not None:
                    if request["reconciliation_digest"] != reconciliation_digest:
                        raise ReconciliationConflict(
                            "request already has a different provider reconciliation"
                        )
                    return _public_request(request, should_send=False)
                if request["status"] != "unknown":
                    raise ReconciliationConflict("only an unknown request can be reconciled")

                if priced_tier is None:
                    cost = _unknown_cost_details(safe_usage, supplier_tier)
                else:
                    cost = calculate_official_usage_cost(
                        safe_usage,
                        model=MODEL,
                        service_tier=priced_tier,
                        processing_mode=PROCESSING_MODE,
                        other_charges_usd=Decimal("0"),
                        other_charges_basis=OTHER_CHARGES_BASIS,
                    )
                actual_cost = cost["official_estimated_total_usd"]
                state = "settled" if isinstance(actual_cost, Decimal) else "unknown"
                bound_exceeded = bool(request["reservation_bound_exceeded"]) or _usage_exceeds_reservation(
                    request, safe_usage
                )
                history = [
                    {
                        "kind": "original_unknown",
                        "result_digest": request["result_digest"],
                        "service_tier": request["supplier_service_tier"],
                        "usage": request["usage"],
                        "cost_details": request["cost_details"],
                        "actual_cost_usd": request["actual_cost_usd"],
                        "http_status": request["http_status"],
                        "status": request["status"],
                    },
                    {
                        "kind": "provider_reconciliation",
                        "evidence_ref": evidence_ref,
                        "digest": reconciliation_digest,
                        "usage": safe_usage,
                        "cost_details": _json_safe(cost),
                        "actual_cost_usd": actual_cost,
                        "http_status": status_code,
                        "status": state,
                    },
                ]
                connection.execute(
                    text(
                        """
                        UPDATE p0_admission.model_requests SET
                            supplier_service_tier=:supplier_service_tier,
                            status=:status,
                            usage=CAST(:usage AS jsonb),
                            cost_details=CAST(:cost_details AS jsonb),
                            actual_cost_usd=:actual_cost_usd,
                            supplier_invoice_amount_usd=NULL,
                            http_status=:http_status,
                            reservation_bound_exceeded=:reservation_bound_exceeded,
                            reconciliation_evidence_ref=:evidence_ref,
                            reconciliation_digest=:reconciliation_digest,
                            reconciliation_history=CAST(:history AS jsonb),
                            updated_at=now()
                        WHERE request_id=:request_id AND status='unknown'
                        """
                    ),
                    {
                        "supplier_service_tier": supplier_tier,
                        "status": state,
                        "usage": json.dumps(safe_usage, separators=(",", ":")),
                        "cost_details": json.dumps(_json_safe(cost), separators=(",", ":")),
                        "actual_cost_usd": actual_cost,
                        "http_status": status_code,
                        "reservation_bound_exceeded": bound_exceeded,
                        "evidence_ref": evidence_ref,
                        "reconciliation_digest": reconciliation_digest,
                        "history": json.dumps(_json_safe(history), separators=(",", ":")),
                        "request_id": request_id,
                    },
                )
                if bound_exceeded:
                    connection.execute(
                        text(
                            "UPDATE p0_admission.task_authority "
                            "SET reservation_bound_exceeded=true, updated_at=now() "
                            "WHERE task_id=:task_id"
                        ),
                        {"task_id": authority["task_id"]},
                    )
                updated = connection.execute(
                    text(
                        "SELECT * FROM p0_admission.model_requests "
                        "WHERE request_id=:request_id"
                    ),
                    {"request_id": request_id},
                ).mappings().one()
                return _public_request(updated, should_send=False)
        except AdmissionError:
            raise
        except (PricingInputError, SQLAlchemyError):
            raise AdmissionStorageError(
                "provider reconciliation failed; details are suppressed"
            ) from None

    def query_request(self, request_id: str) -> dict[str, Any] | None:
        """Return only the persisted request ledger and normalized usage fields."""
        request_id = _identity(request_id, "request_id")
        try:
            with self.engine.connect() as connection:
                row = connection.execute(
                    text("SELECT * FROM p0_admission.model_requests WHERE request_id=:request_id"),
                    {"request_id": request_id},
                ).mappings().first()
                return _public_request(row, should_send=False) if row is not None else None
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "request lookup failed; database details are suppressed"
            ) from None

    def change_scope(
        self,
        scope: ExecutionScope,
        **changes: object,
    ) -> ExecutionScope:
        """Inject a current Task/Session/Run, permission, input, or cancellation change.

        Supported keys are task_status, session_status, run_status, cancel_requested,
        permitted, input_valid, session_id, run_id, and the three revision fields.
        Relevant revisions advance automatically unless explicitly supplied.
        """
        allowed = {
            "task_status", "session_status", "run_status", "cancel_requested",
            "permitted", "input_valid", "session_id", "run_id", *_REVISION_FIELDS,
        }
        if set(changes) - allowed:
            raise AdmissionInputError("unsupported scope change field")
        values = {key: value for key, value in changes.items() if value is not None}
        if not values:
            return scope
        if "task_status" in values and values["task_status"] not in _TASK_STATUSES:
            raise AdmissionInputError("unsupported Task status")
        if "session_status" in values and values["session_status"] not in _SESSION_STATUSES:
            raise AdmissionInputError("unsupported Session status")
        if "run_status" in values and values["run_status"] not in _RUN_STATUSES:
            raise AdmissionInputError("unsupported Run status")
        for flag in ("cancel_requested", "permitted", "input_valid"):
            if flag in values and type(values[flag]) is not bool:
                raise AdmissionInputError(f"{flag} must be boolean")
        for identity_field in ("session_id", "run_id"):
            if identity_field in values:
                values[identity_field] = _identity(values[identity_field], identity_field)
        for revision_field in _REVISION_FIELDS:
            if revision_field in values:
                values[revision_field] = _revision(values[revision_field], revision_field)
        try:
            with self.engine.begin() as connection:
                row = self._locked_authority(connection, scope, "change_scope", enforce_gate=False)
                changed_control = any(
                    key in values and values[key] != row[key]
                    for key in ("task_status", "cancel_requested", "session_status", "run_status")
                )
                changed_permission = "permitted" in values and values["permitted"] != row["permitted"]
                changed_input = "input_valid" in values and values["input_valid"] != row["input_valid"]
                changed_input = changed_input or (
                    "input_revision" in values
                    and values["input_revision"] != row["input_revision"]
                )
                if changed_control and "control_revision" not in values:
                    values["control_revision"] = _next_revision(row["control_revision"])
                if changed_permission and "permission_revision" not in values:
                    values["permission_revision"] = _next_revision(row["permission_revision"])
                if changed_input and "input_revision" not in values:
                    values["input_revision"] = _next_revision(row["input_revision"])
                updates = {key: value for key, value in values.items() if value != row[key]}
                if updates:
                    assignments = ", ".join(f"{key}=:{key}" for key in updates)
                    connection.execute(
                        text(
                            "UPDATE p0_admission.task_authority SET "
                            f"{assignments}, updated_at=now() WHERE task_id=:task_id"
                        ),
                        {**updates, "task_id": scope.task_id},
                    )
                latest = {**row, **updates}
                return ExecutionScope(
                    task_id=latest["task_id"],
                    session_id=latest["session_id"],
                    run_id=latest["run_id"],
                    control_revision=latest["control_revision"],
                    permission_revision=latest["permission_revision"],
                    input_revision=latest["input_revision"],
                )
        except AdmissionError:
            raise
        except SQLAlchemyError:
            raise AdmissionStorageError(
                "scope change failed; database details are suppressed"
            ) from None

    def _locked_authority(
        self,
        connection: Connection,
        scope: ExecutionScope,
        action: str,
        *,
        enforce_gate: bool = True,
    ) -> Mapping[str, Any]:
        _require_transaction(connection)
        _identity(action, "action")
        row = connection.execute(
            text("SELECT * FROM p0_admission.task_authority WHERE task_id=:task_id FOR UPDATE"),
            {"task_id": _identity(scope.task_id, "task_id")},
        ).mappings().first()
        if row is None:
            raise GateDenied("current Task authority is unavailable")
        for field in _SCOPE_FIELDS:
            expected = _scope_values(scope)[field]
            if row[field] != expected:
                raise GateDenied("scope identity or revision is stale")
        if not enforce_gate:
            return row
        if row["reservation_bound_exceeded"]:
            raise GateDenied("ordinary admission is closed after a reservation bound was exceeded")
        if row["task_status"] != "active":
            raise GateDenied("Task is not eligible for ordinary progress")
        if row["cancel_requested"]:
            raise GateDenied("Task cancellation is requested")
        if not row["permitted"]:
            raise GateDenied("current permission denies ordinary progress")
        if not row["input_valid"]:
            raise GateDenied("current input revision is invalid")
        if row["session_status"] not in {"queued", "running"}:
            raise GateDenied("Session is not eligible for ordinary progress")
        if row["run_status"] not in {"queued", "running"}:
            raise GateDenied("Run is not eligible for ordinary progress")
        return row


def _existing_reservation(
    row: Mapping[str, Any], expected_scope: Mapping[str, str], digest: str
) -> dict[str, Any]:
    if any(row[field] != expected_scope[field] for field in _SCOPE_FIELDS):
        raise ScopeConflict("request identity was reused from a different ExecutionScope")
    if row["request_digest"] != digest:
        raise IdempotencyConflict("request identity was reused with a different digest")
    return _public_request(row, should_send=False)


def _validate_reconciliation_scope(
    authority: Mapping[str, Any], scope: ExecutionScope
) -> None:
    expected = _scope_values(scope)
    if any(authority[field] != expected[field] for field in _SCOPE_FIELDS):
        raise ScopeConflict("reconciliation scope is not the current Task authority")
    if not authority["permitted"]:
        raise GateDenied("current permission denies provider reconciliation")


def _usage_exceeds_reservation(
    request: Mapping[str, Any], usage: dict[str, int | None] | None
) -> bool:
    if usage is None:
        return False
    return (
        usage["input_tokens"] is not None
        and usage["input_tokens"] > request["input_tokens_upper_bound"]
    ) or (
        usage["output_tokens"] is not None
        and usage["output_tokens"] > request["max_output_tokens"]
    )


def _provider_evidence_ref(value: object) -> str:
    if not isinstance(value, str) or not _EVIDENCE_REF_RE.fullmatch(value):
        raise AdmissionInputError(
            "provider_evidence_ref must be a bounded opaque reference without query data"
        )
    return value


def _reconciliation_digest(
    evidence_ref: str,
    usage: dict[str, int | None] | None,
    service_tier: str,
    http_status: int | None,
) -> str:
    payload = {
        "provider_evidence_ref": evidence_ref,
        "usage": usage,
        "service_tier": service_tier,
        "http_status": http_status,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _require_transaction(connection: Connection) -> None:
    if not isinstance(connection, Connection) or not connection.in_transaction():
        raise AdmissionInputError("an active SQLAlchemy transaction is required")


def _scope_values(scope: ExecutionScope) -> dict[str, str]:
    if not isinstance(scope, ExecutionScope):
        raise AdmissionInputError("scope must be an ExecutionScope")
    return {
        "task_id": _identity(scope.task_id, "task_id"),
        "session_id": _identity(scope.session_id, "session_id"),
        "run_id": _identity(scope.run_id, "run_id"),
        "control_revision": _revision(scope.control_revision, "control_revision"),
        "permission_revision": _revision(scope.permission_revision, "permission_revision"),
        "input_revision": _revision(scope.input_revision, "input_revision"),
    }


def _identity(value: object, field: str) -> str:
    if isinstance(value, uuid.UUID):
        value = str(value)
    if not isinstance(value, str) or not value.strip() or len(value) > 240:
        raise AdmissionInputError(f"{field} must be a non-empty identifier")
    return value.strip()


def _revision(value: object, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise AdmissionInputError(f"{field} must be a string or integer revision")
    rendered = str(value).strip()
    if not rendered or len(rendered) > 160:
        raise AdmissionInputError(f"{field} must be a non-empty revision")
    return rendered


def _next_revision(value: str) -> str:
    try:
        return str(int(value) + 1)
    except ValueError:
        return f"{value}.next"


def _money(value: object, field: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise AdmissionInputError(f"{field} must be a non-negative finite Decimal")
    return value


def _token_count(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise AdmissionInputError(f"{field} must be a non-negative integer")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise AdmissionInputError("request_digest must be a SHA-256 hex digest")
    return value.removeprefix("sha256:").lower()


def _http_status(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 100 <= value <= 599:
        raise AdmissionInputError("http_status must be between 100 and 599 or null")
    return value


def _service_tiers(service_tier: object) -> tuple[str, str | None]:
    if not isinstance(service_tier, str) or not re.fullmatch(r"[a-z0-9_-]{1,48}", service_tier):
        raise AdmissionInputError("service_tier must be a bounded provider tier name")
    if service_tier == "default":
        return "default", PRICE_SERVICE_TIER
    if service_tier == PRICE_SERVICE_TIER:
        return PRICE_SERVICE_TIER, PRICE_SERVICE_TIER
    return service_tier, None


def _normalise_usage(usage: Mapping[str, object] | None) -> dict[str, int | None] | None:
    if usage is None:
        return None
    if not isinstance(usage, Mapping):
        raise AdmissionInputError("supplier usage must be a mapping or null")
    details = usage.get("input_tokens_details")
    if details is not None and not isinstance(details, Mapping):
        raise AdmissionInputError("supplier token details must be a mapping or null")

    def value(flat_keys: tuple[str, ...], nested_key: str | None = None) -> int | None:
        candidates = [usage[key] for key in flat_keys if key in usage]
        if nested_key is not None and isinstance(details, Mapping) and nested_key in details:
            candidates.append(details[nested_key])
        normalized: list[int | None] = []
        for candidate in candidates:
            if candidate is not None and (type(candidate) is not int or candidate < 0):
                raise AdmissionInputError("supplier token usage must contain non-negative integers")
            normalized.append(candidate)
        known = {candidate for candidate in normalized if candidate is not None}
        if len(known) > 1:
            raise AdmissionInputError("supplier token usage fields conflict")
        return next(iter(known)) if known else None

    return {
        "input_tokens": value(("input_tokens",)),
        "cached_input_tokens": value(("cached_input_tokens",), "cached_tokens"),
        "cache_write_tokens": value(("cache_write_tokens",), "cache_write_tokens"),
        "output_tokens": value(("output_tokens",)),
    }


def _result_digest(
    usage: dict[str, int | None] | None, service_tier: str, http_status: int | None
) -> str:
    payload = json.dumps(
        {"usage": usage, "service_tier": service_tier, "http_status": http_status},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _unknown_cost_details(
    usage: dict[str, int | None] | None, supplier_tier: str
) -> dict[str, Any]:
    return {
        "provider": "openai",
        "model": MODEL,
        "service_tier": supplier_tier,
        "processing_mode": PROCESSING_MODE,
        "currency": "USD",
        "price_revision": PRICE_REVISION,
        "usage": usage,
        "official_model_token_amount_usd": None,
        "official_estimated_total_usd": None,
        "supplier_invoice_amount_usd": None,
        "supplier_invoice_status": "not_provided",
        "unknown_reasons": ["unsupported_service_tier"],
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if value is None or type(value) in {str, int, float, bool}:
        return value
    return str(value)


def _public_gate(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "permitted": True,
        "task_id": row["task_id"],
        "session_id": row["session_id"],
        "run_id": row["run_id"],
        "control_revision": row["control_revision"],
        "permission_revision": row["permission_revision"],
        "input_revision": row["input_revision"],
    }


def _public_request(row: Mapping[str, Any], *, should_send: bool) -> dict[str, Any]:
    return {
        "request_id": row["request_id"],
        "request_digest": row["request_digest"],
        "task_id": row["task_id"],
        "session_id": row["session_id"],
        "run_id": row["run_id"],
        "control_revision": row["control_revision"],
        "permission_revision": row["permission_revision"],
        "input_revision": row["input_revision"],
        "model": row["model"],
        "price_revision": row["price_revision"],
        "service_tier": row["supplier_service_tier"],
        "status": row["status"],
        "result_digest": row["result_digest"],
        "reservation_usd": format(row["reservation_usd"], "f"),
        "reservation_bound_exceeded": row["reservation_bound_exceeded"],
        "reservation_details": row["reservation_details"],
        "usage": row["usage"],
        "actual_cost_usd": (
            format(row["actual_cost_usd"], "f")
            if row["actual_cost_usd"] is not None
            else None
        ),
        "supplier_invoice_amount_usd": None,
        "cost_details": row["cost_details"],
        "reconciliation_evidence_ref": row["reconciliation_evidence_ref"],
        "reconciliation_digest": row["reconciliation_digest"],
        "reconciliation_history": row["reconciliation_history"],
        "http_status": row["http_status"],
        "should_send": should_send,
    }
