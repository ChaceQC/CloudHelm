"""Exercise PydanticAI follow-up requests through current admission and money gates.

All Responses API bodies below are fixed local fixtures. They contain no supplier
usage, so the business ledger must retain each sent request as unknown. This is
an SDK/admission seam check, not a supplier or price-evidence run.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from openai import AsyncOpenAI
from sqlalchemy import create_engine

from integrations.model_pricing import calculate_reservation_upper_bound
from integrations.seam_admission import (
    BudgetExceeded,
    ExecutionScope,
    GateDenied,
    SeamAdmission,
)
from integrations.seam_stream import MoneyGuardTransport
from scripts.p0.admitted_path_fixtures import (
    OUTPUT_CAP,
    agent_for_path,
    fixture_response,
    response_body,
)
from scripts.p0.model_boundary import (
    AdmissionDenied,
    AdmissionTransport,
    BASE_URL,
    MODEL_NAME,
    RequestBudget,
    RequestJournal,
)

DATABASE_URL = "postgresql+psycopg://cloudhelm_probe@127.0.0.1:55432/cloudhelm_p0"
INPUT_BOUND = 65536
_OTHER_CHARGES_BASIS = "custom function tools only; no billed OpenAI hosted tools"


def _reservation_bound() -> Decimal:
    details = calculate_reservation_upper_bound(
        model=MODEL_NAME,
        service_tier="standard",
        processing_mode="global",
        input_tokens_upper_bound=INPUT_BOUND,
        max_output_tokens=OUTPUT_CAP,
        other_charges_upper_bound_usd=Decimal("0"),
        other_charges_basis=_OTHER_CHARGES_BASIS,
    )
    bound = details["reservation_upper_bound_usd"]
    if not isinstance(bound, Decimal) or bound <= 0:
        raise AssertionError("fixed request reservation bound is unavailable")
    return bound


async def _run_case(
    admission: SeamAdmission,
    path: str,
    mode: str,
    denied_by: str | None,
    reservation: Decimal,
) -> dict[str, Any]:
    prefix = f"a02b-{uuid.uuid4().hex}"
    scope = ExecutionScope(
        f"{prefix}-task", f"{prefix}-session", f"{prefix}-run", "r1", "r1", "r1"
    )
    admission.seed_scope(scope, reservation * (2 if mode == "allow" else 1))
    calls = 0
    expected_calls = 2 if mode == "allow" else 1

    async def fixture(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls > expected_calls:
            raise AssertionError("unexpected fixture request")
        first = calls == 1
        if path == "sdk_retry" and first:
            status, body = 500, b'{"error":{"message":"fixed fixture","type":"server_error"}}'
        else:
            status = 200
            if path == "validator_repair":
                answer = "first" if first else "accepted"
                text = json.dumps({"answer": answer}, separators=(",", ":"))
            elif path == "summary_compaction" and first:
                text = json.dumps({"summary": "bounded fixed summary"}, separators=(",", ":"))
            else:
                text = "first" if first else "continued"
            body = response_body(
                MODEL_NAME,
                text,
                calls,
                final_result=(path == "validator_repair" or path == "summary_compaction" and first),
            )

        after_read = None
        if first and denied_by == "revoke":
            after_read = lambda: admission.change_scope(scope, permitted=False)
        return fixture_response(request, status, body, after_read)

    with tempfile.TemporaryDirectory(prefix="cloudhelm-a02b-") as temp_dir:
        journal = RequestJournal(
            Path(temp_dir) / "requests.sqlite3",
            f"{prefix}-{path}-{mode}",
            max_requests=2,
            max_reserved_output_tokens=2 * OUTPUT_CAP,
        )
        budget = RequestBudget(journal)
        money = MoneyGuardTransport(budget, admission, scope)
        money.inner = httpx.MockTransport(fixture)
        transport = AdmissionTransport(money, budget, live=False)
        http_client = httpx.AsyncClient(transport=transport, timeout=10)
        sdk = AsyncOpenAI(
            api_key="fixed-local-fixture-key",
            base_url=BASE_URL,
            http_client=http_client,
            max_retries=1 if path == "sdk_retry" else 0,
        )
        agent = agent_for_path(sdk, path)
        caught: BaseException | None = None
        summary_completed = False
        output_correct = False
        try:
            with transport.scenario(path, max_logical_calls=2):
                if path == "summary_compaction":
                    summary_agent, continuation_agent = agent
                    summary = await summary_agent.run(
                        "Summarize in one sentence: A deployment is ready only after the artifact, "
                        "configuration, approval, and current target checks are recorded."
                    )
                    summary_completed = summary.output.summary == "bounded fixed summary"
                    continuation = await continuation_agent.run(
                        "Continue from this compacted summary and name the next safe check: "
                        f"{summary.output.summary[:240]}"
                    )
                    output_correct = continuation.output == "continued"
                elif path == "validator_repair":
                    result = await agent.run("Produce one fixed probe result.")
                    output_correct = result.output.answer == "accepted"
                else:
                    result = await agent.run("Produce one fixed probe result.")
                    output_correct = result.output == "continued"
        except Exception as exc:
            caught = exc
        finally:
            await http_client.aclose()

        local = journal.records()
        local_by_id = {item.request_record_id: item for item in local}
        business = [admission.query_request(item.request_record_id) for item in budget.records]
        exception_chain: list[BaseException] = []
        cursor = caught
        while cursor is not None and cursor not in exception_chain:
            exception_chain.append(cursor)
            cursor = cursor.__cause__ or cursor.__context__
        expected_denial = (
            (denied_by == "revoke" and any(isinstance(e, GateDenied) for e in exception_chain))
            or (denied_by == "budget" and any(isinstance(e, BudgetExceeded) for e in exception_chain))
        )
        denial_type = next(
            (type(e).__name__ for e in exception_chain
             if isinstance(e, (GateDenied, BudgetExceeded, AdmissionDenied))),
            "none",
        )
        expected_allow = mode == "allow" and caught is None and output_correct
        visible = all(item.preflight_commit_visible for item in local)
        unknown_business = sum(row is not None and row["status"] == "unknown" for row in business)
        second_local_unknown = bool(
            len(budget.records) == 2
            and local_by_id[budget.records[1].request_record_id].journal_outcome == "unknown"
        )
        passed = (
            len(local) == 2
            and calls == expected_calls
            and money.sent == expected_calls
            and visible
            and (
                (expected_allow and len([row for row in business if row is not None]) == 2
                 and unknown_business == 2)
                or (denied_by is not None and expected_denial and len(business) == 2
                    and business[0] is not None and business[1] is None
                    and unknown_business == 1 and second_local_unknown)
            )
            and (path != "summary_compaction" or summary_completed)
        )
        return {
            "path": path,
            "mode": mode,
            "denied_by": denied_by or "none",
            "denial_type": denial_type,
            "passed": passed,
            "sdk_local_requests": len(local),
            "business_reservations": sum(row is not None for row in business),
            "business_unknown": unknown_business,
            "local_unknown": sum(item.journal_outcome == "unknown" for item in local),
            "fixture_http": calls,
            "money_guard_http": money.sent,
            "preflight_visible": visible,
            "output_correct": output_correct,
            "summary_completed": summary_completed,
            "compaction_method": (
                "controlled_summary_agent" if path == "summary_compaction" else "none"
            ),
            "synthetic_usage": False,
            "supplier_cost": "unknown",
        }


async def _main() -> int:
    engine = create_engine(DATABASE_URL, pool_size=2, max_overflow=0, hide_parameters=True)
    admission = SeamAdmission(engine)
    try:
        admission.bootstrap()
        reservation = _reservation_bound()
        cases = (
            ("validator_repair", "allow", None),
            ("validator_repair", "deny", "revoke"),
            ("sdk_retry", "allow", None),
            ("sdk_retry", "deny", "budget"),
            ("summary_compaction", "allow", None),
            ("summary_compaction", "deny", "revoke"),
        )
        passed = True
        for path, mode, denied_by in cases:
            try:
                result = await _run_case(admission, path, mode, denied_by, reservation)
            except Exception as exc:
                result = {"path": path, "mode": mode, "passed": False,
                          "error_type": type(exc).__name__, "details": "suppressed"}
            print(json.dumps(result, separators=(",", ":")))
            passed = passed and result.get("passed") is True
        print(json.dumps({"check": "P0.1-A02b", "passed": passed}, separators=(",", ":")))
        return 0 if passed else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_main()))
    except Exception as exc:
        print(json.dumps({"check": "P0.1-A02b", "passed": False,
                          "error_type": type(exc).__name__, "details": "suppressed"}))
        raise SystemExit(1) from None
