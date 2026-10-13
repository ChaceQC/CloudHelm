"""Focused database-backed checks for the isolated P0 admission seam."""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations.model_pricing import calculate_reservation_upper_bound
from integrations.seam_admission import (
    AdmissionInputError,
    BudgetExceeded,
    ExecutionScope,
    GateDenied,
    IdempotencyConflict,
    ReconciliationConflict,
    ScopeConflict,
    SeamAdmission,
)

_DATABASE_URL = "postgresql+psycopg://cloudhelm_probe@127.0.0.1:55432/cloudhelm_p0"


def _scope(prefix: str) -> ExecutionScope:
    return ExecutionScope(
        task_id=f"{prefix}-task",
        session_id=f"{prefix}-session",
        run_id=f"{prefix}-run",
        control_revision="1",
        permission_revision="1",
        input_revision="1",
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _expect_gate_denied(action: Callable[[], object]) -> None:
    try:
        action()
    except GateDenied:
        return
    raise AssertionError("current gate accepted stale or ineligible scope")


def _expect_rejected(action: Callable[[], object], expected: type[Exception]) -> None:
    try:
        action()
    except expected:
        return
    raise AssertionError("admission accepted a rejected request")


def main() -> int:
    run_id = uuid.uuid4().hex
    prefix = f"admission-check-{run_id}"
    primary = _scope(prefix)
    cancel_scope = _scope(f"{prefix}-cancel")
    revoke_scope = _scope(f"{prefix}-revoke")
    invalid_input_scope = _scope(f"{prefix}-input")
    small_budget_scope = _scope(f"{prefix}-budget")
    unsupported_tier_scope = _scope(f"{prefix}-tier")
    bound_scope = _scope(f"{prefix}-bound")
    reconcile_scope = _scope(f"{prefix}-reconcile")
    engine = create_engine(
        _DATABASE_URL,
        connect_args={"connect_timeout": 3},
        pool_pre_ping=True,
    )
    admission = SeamAdmission(engine)
    request_id = f"{prefix}-request"
    second_request_id = f"{prefix}-second-request"
    overflow_request_id = f"{prefix}-overflow"
    tier_request_id = f"{prefix}-tier-request"
    bound_request_id = f"{prefix}-bound-request"
    reconcile_request_id = f"{prefix}-reconcile-request"
    fixtures = (
        primary,
        cancel_scope,
        revoke_scope,
        invalid_input_scope,
        small_budget_scope,
        unsupported_tier_scope,
        bound_scope,
        reconcile_scope,
    )
    try:
        admission.bootstrap()
        admission.bootstrap()
        bound = calculate_reservation_upper_bound(
            model="gpt-6-luna",
            service_tier="standard",
            processing_mode="global",
            input_tokens_upper_bound=5000,
            max_output_tokens=1000,
            other_charges_upper_bound_usd=Decimal("0"),
            other_charges_basis=(
                "custom function tools only; no billed OpenAI hosted tools"
            ),
        )["reservation_upper_bound_usd"]
        assert isinstance(bound, Decimal) and bound > 0
        admission.seed_scope(primary, bound)
        admission.seed_scope(cancel_scope, Decimal("1"))
        admission.seed_scope(revoke_scope, Decimal("1"))
        admission.seed_scope(invalid_input_scope, Decimal("1"))
        admission.seed_scope(small_budget_scope, Decimal("0"))
        admission.seed_scope(unsupported_tier_scope, Decimal("1"))
        bound_reservation = calculate_reservation_upper_bound(
            model="gpt-6-luna",
            service_tier="standard",
            processing_mode="global",
            input_tokens_upper_bound=65536,
            max_output_tokens=1,
            other_charges_upper_bound_usd=Decimal("0"),
            other_charges_basis=(
                "custom function tools only; no billed OpenAI hosted tools"
            ),
        )["reservation_upper_bound_usd"]
        assert isinstance(bound_reservation, Decimal)
        admission.seed_scope(bound_scope, bound_reservation)
        admission.seed_scope(reconcile_scope, Decimal("1"))

        assert admission.check_current(primary, "model_request")["permitted"] is True
        with engine.begin() as connection:
            joined = admission.check_current(primary, "gateway_write", connection=connection)
            assert joined["task_id"] == primary.task_id
            connection.execute(text("SELECT 1"))

        first = admission.reserve_request(
            primary, request_id, _digest("first model request"), 5000, 1000
        )
        assert first["should_send"] is True
        repeated = admission.reserve_request(
            primary, request_id, _digest("first model request"), 5000, 1000
        )
        assert repeated["should_send"] is False
        _expect_rejected(
            lambda: admission.reserve_request(
                primary, request_id, _digest("different request"), 5000, 1000
            ),
            IdempotencyConflict,
        )
        for mismatch in (
            ExecutionScope(
                primary.task_id,
                f"{primary.session_id}-other",
                primary.run_id,
                primary.control_revision,
                primary.permission_revision,
                primary.input_revision,
            ),
            ExecutionScope(
                primary.task_id,
                primary.session_id,
                f"{primary.run_id}-other",
                primary.control_revision,
                primary.permission_revision,
                primary.input_revision,
            ),
            ExecutionScope(
                primary.task_id,
                primary.session_id,
                primary.run_id,
                "2",
                primary.permission_revision,
                primary.input_revision,
            ),
            ExecutionScope(
                primary.task_id,
                primary.session_id,
                primary.run_id,
                primary.control_revision,
                "2",
                primary.input_revision,
            ),
            ExecutionScope(
                primary.task_id,
                primary.session_id,
                primary.run_id,
                primary.control_revision,
                primary.permission_revision,
                "2",
            ),
        ):
            _expect_rejected(
                lambda mismatch=mismatch: admission.reserve_request(
                    mismatch, request_id, _digest("first model request"), 5000, 1000
                ),
                ScopeConflict,
            )

        unknown = admission.record_result(
            request_id,
            {"input_tokens": 4800, "output_tokens": 73},
            service_tier="default",
            http_status=200,
        )
        assert unknown["status"] == "unknown"
        assert unknown["actual_cost_usd"] is None
        assert unknown["supplier_invoice_amount_usd"] is None
        assert unknown["service_tier"] == "default"
        assert unknown["cost_details"]["service_tier"] == "standard"
        assert unknown["usage"]["cache_write_tokens"] is None
        assert admission.reserve_request(
            primary, request_id, _digest("first model request"), 5000, 1000
        )["should_send"] is False
        _expect_rejected(
            lambda: admission.reserve_request(
                primary, second_request_id, _digest("second request"), 1, 1
            ),
            BudgetExceeded,
        )
        saved = admission.query_request(request_id)
        assert saved is not None and saved["status"] == "unknown"
        assert saved["actual_cost_usd"] is None
        assert saved["supplier_invoice_amount_usd"] is None

        changed_cancel = admission.change_scope(cancel_scope, cancel_requested=True)
        assert changed_cancel.control_revision != cancel_scope.control_revision
        _expect_gate_denied(lambda: admission.check_current(cancel_scope, "model_request"))
        _expect_gate_denied(lambda: admission.check_current(changed_cancel, "model_request"))

        changed_revoke = admission.change_scope(revoke_scope, permitted=False)
        assert changed_revoke.permission_revision != revoke_scope.permission_revision
        _expect_gate_denied(lambda: admission.check_current(revoke_scope, "model_request"))
        _expect_gate_denied(lambda: admission.check_current(changed_revoke, "model_request"))

        changed_input = admission.change_scope(
            invalid_input_scope, input_revision="2", input_valid=False
        )
        _expect_gate_denied(
            lambda: admission.check_current(invalid_input_scope, "model_request")
        )
        _expect_gate_denied(
            lambda: admission.check_current(changed_input, "model_request")
        )

        _expect_rejected(
            lambda: admission.reserve_request(
                small_budget_scope, overflow_request_id, _digest("overflow"), 1, 1
            ),
            BudgetExceeded,
        )
        admission.reserve_request(
            unsupported_tier_scope,
            tier_request_id,
            _digest("unsupported tier"),
            100,
            10,
        )
        unsupported_tier = admission.record_result(
            tier_request_id,
            {
                "input_tokens": 90,
                "cached_input_tokens": 0,
                "cache_write_tokens": 0,
                "output_tokens": 5,
            },
            service_tier="priority",
            http_status=200,
        )
        assert unsupported_tier["status"] == "unknown"
        assert unsupported_tier["actual_cost_usd"] is None
        assert unsupported_tier["cost_details"]["unknown_reasons"] == [
            "unsupported_service_tier"
        ]

        bound_reserved = admission.reserve_request(
            bound_scope,
            bound_request_id,
            _digest("bound-exceeded supplier response"),
            65536,
            1,
        )
        assert bound_reserved["reservation_details"]["input_tokens_upper_bound"] == 65536
        bound_result = admission.record_result(
            bound_request_id,
            {
                "input_tokens": 272001,
                "cached_input_tokens": 0,
                "cache_write_tokens": 0,
                "output_tokens": 1,
            },
            service_tier="default",
            http_status=200,
        )
        assert bound_result["reservation_bound_exceeded"] is True
        assert bound_result["usage"]["input_tokens"] == 272001
        assert bound_result["actual_cost_usd"] is not None
        assert bound_result["cost_details"]["input_tokens"] == 272001
        assert (
            bound_result["actual_cost_usd"]
            == bound_result["cost_details"]["official_estimated_total_usd"]
        )
        assert bound_result["supplier_invoice_amount_usd"] is None
        with engine.connect() as connection:
            task_closed = connection.execute(
                text(
                    "SELECT reservation_bound_exceeded FROM "
                    "p0_admission.task_authority WHERE task_id=:task_id"
                ),
                {"task_id": bound_scope.task_id},
            ).scalar_one()
        assert task_closed is True
        _expect_gate_denied(lambda: admission.check_current(bound_scope, "model_request"))
        _expect_gate_denied(
            lambda: admission.reserve_request(
                bound_scope, f"{prefix}-after-bound", _digest("blocked"), 1, 1
            )
        )

        admission.reserve_request(
            reconcile_scope,
            reconcile_request_id,
            _digest("synthetic unknown response"),
            100,
            10,
        )
        synthetic_unknown = admission.record_result(
            reconcile_request_id,
            {"input_tokens": 20, "output_tokens": 2},
            service_tier="default",
            http_status=200,
        )
        assert synthetic_unknown["status"] == "unknown"
        original_unknown_digest = synthetic_unknown["result_digest"]
        terminal_reconcile_scope = admission.change_scope(
            reconcile_scope,
            task_status="cancelled",
            cancel_requested=True,
            session_status="completed",
            run_status="succeeded",
        )
        complete_usage = {
            "input_tokens": 20,
            "cached_input_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 2,
        }
        _expect_rejected(
            lambda: admission.reconcile_result(
                reconcile_scope,
                reconcile_request_id,
                complete_usage,
                None,
            ),
            AdmissionInputError,
        )
        evidence_ref = f"provider-evidence://synthetic-probe/{run_id}"
        reconciled = admission.reconcile_result(
            terminal_reconcile_scope,
            reconcile_request_id,
            complete_usage,
            evidence_ref,
            service_tier="default",
            http_status=200,
        )
        assert reconciled["status"] == "settled"
        assert reconciled["actual_cost_usd"] is not None
        assert reconciled["supplier_invoice_amount_usd"] is None
        assert reconciled["reconciliation_evidence_ref"] == evidence_ref
        assert reconciled["reconciliation_history"][0]["result_digest"] == original_unknown_digest
        assert reconciled["reconciliation_history"][0]["status"] == "unknown"
        reconciled_again = admission.reconcile_result(
            terminal_reconcile_scope,
            reconcile_request_id,
            complete_usage,
            evidence_ref,
            service_tier="default",
            http_status=200,
        )
        assert reconciled_again == reconciled
        _expect_rejected(
            lambda: admission.reconcile_result(
                terminal_reconcile_scope,
                reconcile_request_id,
                complete_usage,
                f"provider-evidence://different/{run_id}",
                service_tier="default",
                http_status=200,
            ),
            ReconciliationConflict,
        )
        print(
            json.dumps(
                {
                    "check": "p0.1-A01b admission",
                    "result": "passed",
                    "database": "cloudhelm_p0",
                    "schema": "p0_admission",
                    "coverage": [
                        "same-transaction current gate",
                        "cancellation and stale control revision",
                        "revocation and stale permission revision",
                        "invalid input and stale input revision",
                        "budget overflow",
                        "request replay and digest conflict",
                        "unknown usage keeps reservation occupied",
                        "unsupported priority tier remains unknown",
                        "actual usage beyond the reserved input bound closes admission",
                        "synthetic unknown reconciles after cancellation and Run completion",
                        "reconciliation requires bounded evidence and is idempotent once",
                        "admission schema migration is idempotent",
                        "request identity binds the full ExecutionScope",
                    ],
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        try:
            with engine.begin() as connection:
                for fixture in fixtures:
                    connection.execute(
                        text("DELETE FROM p0_admission.model_requests WHERE task_id=:task_id"),
                        {"task_id": fixture.task_id},
                    )
                    connection.execute(
                        text("DELETE FROM p0_admission.task_authority WHERE task_id=:task_id"),
                        {"task_id": fixture.task_id},
                    )
        finally:
            engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "check": "p0.1-A01b admission",
                    "result": "failed",
                    "error_type": type(exc).__name__,
                    "details": "suppressed",
                },
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None
