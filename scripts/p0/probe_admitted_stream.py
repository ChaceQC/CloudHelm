"""P0.1-A01 bounded real supplier stream with business gates and safe DBOS steps."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import httpx
from dbos import DBOS, DBOSConfig, SetWorkflowID
from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import FunctionToolCallEvent
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy import create_engine

from integrations.seam_admission import ExecutionScope, SeamAdmission
from integrations.seam_checkpoint import CheckpointStore, ContextReferences
from integrations.seam_gateway import AdmittedGateway
from integrations.seam_stream import MoneyGuardTransport
from scripts.p0.gateway_probe import Gateway
from scripts.p0.model_boundary import (
    AdmissionTransport, JOURNAL_PATH, MODEL_NAME, RequestBudget, RequestJournal,
    _authorized_config,
)

DSN = "postgresql+psycopg://cloudhelm_probe@127.0.0.1:55432/cloudhelm_p0"
CANDIDATE = "SDK-A01-C1"
engine = create_engine(DSN, pool_size=2, max_overflow=0, hide_parameters=True)
admission = SeamAdmission(engine)
checkpoints = CheckpointStore(engine)
LIVE_ENABLED = False
JOURNAL: RequestJournal | None = None


def scope_for(scenario: str) -> ExecutionScope:
    return ExecutionScope(f"a01-{scenario}", f"a01-session-{scenario}",
                          f"a01-run-{scenario}", "r1", "r1", "r1")


@DBOS.step(name="p0.a01.current_admitted_supplier_turn")
async def supplier_turn(checkpoint_id: str, scenario: str) -> dict[str, Any]:
    """Resolve refs in memory, return finite facts; no SDK histories in checkpoints."""
    if not LIVE_ENABLED or JOURNAL is None:
        raise RuntimeError("P0_LIVE_SCOPE_NOT_OPEN")
    checkpoints.get(checkpoint_id)
    scope = scope_for(scenario)
    gateway = AdmittedGateway(f"a01-{scenario}", admission, scope)
    config = _authorized_config()
    budget = RequestBudget(JOURNAL)
    money = MoneyGuardTransport(budget, admission, scope,
                               disconnect_request=2 if scenario == "disconnect" else None)
    transport = AdmissionTransport(money, budget, live=True, expected_config=config)
    accepted: list[dict[str, Any]] = []
    tool_events = 0
    outcome = "completed"
    error_type: str | None = None

    async def events(ctx: Any, event_stream: Any) -> None:
        nonlocal tool_events
        async for event in event_stream:
            if isinstance(event, FunctionToolCallEvent):
                tool_events += 1

    try:
        async with AsyncOpenAI(
            api_key=config.credential, base_url=config.base_url,
            http_client=httpx.AsyncClient(transport=transport, timeout=45), max_retries=0,
        ) as client:
            agent = Agent(
                OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client)),
                instructions="Call submit_operation exactly once with amount=1. It returns an accepted receipt. After the receipt, respond only submitted. Never call it twice.",
                model_settings={"max_tokens": 512, "openai_reasoning_effort": "max",
                                "openai_service_tier": "default"}, retries=0,
            )

            @agent.tool
            def submit_operation(ctx: RunContext[Any], amount: int) -> dict[str, Any]:
                """Submit one bounded isolated counter operation with amount equal to 1."""
                if amount != 1:
                    raise ValueError("P0_AMOUNT_REJECTED")
                receipt, _ = gateway.submit_operation(
                    idempotency_key="one-effect", tool_call_id=ctx.tool_call_id or "p0-call",
                    args={"amount": amount}, policy_revision=gateway.gate.revision,
                )
                accepted.append(receipt)
                # Isolated executor completion is a separate Gateway command.
                gateway.complete_operation(
                    operation_id=receipt["operation_id"], expected_digest=receipt["request_digest"],
                    result_id="a01-result-1", result={"counter_delta": 1},
                    policy_revision=gateway.gate.revision,
                )
                return receipt

            with transport.scenario(scenario, max_logical_calls=2, require_stream=True):
                await agent.run("Submit the authorized isolated operation now.",
                                event_stream_handler=events)
    except Exception as exc:
        outcome = "unknown"
        error_type = type(exc).__name__
    finally:
        await transport.aclose()
    if not accepted:
        return {"outcome": outcome, "error_type": error_type,
                "real_http": money.sent, "tool_events": tool_events, "operation_ref": None}
    receipt = accepted[0]
    # A repeated callback and the disconnected caller reconcile the original identity.
    same_receipt, created = gateway.submit_operation(
        idempotency_key="one-effect", tool_call_id="duplicate-callback",
        args={"amount": 1}, policy_revision=gateway.gate.revision,
    )
    final = gateway.await_operation(
        operation_id=receipt["operation_id"], expected_digest=receipt["request_digest"],
        policy_revision=gateway.gate.revision,
    )
    facts = gateway.evidence_snapshot(policy_revision=gateway.gate.revision)
    if created or same_receipt != receipt or final is None:
        raise RuntimeError("P0_OPERATION_RECONCILIATION_FAILED")
    return {"outcome": outcome, "error_type": error_type, "real_http": money.sent,
            "tool_events": tool_events, "operation_ref": receipt["operation_id"],
            "accepted_receipt": receipt, "facts": facts, "requests": money.evidence,
            "duplicate_created": created, "result_reconciled": True}


@DBOS.workflow(name="p0.a01.safe_agent_run")
async def safe_agent_run(checkpoint_id: str, scenario: str) -> dict[str, Any]:
    return await supplier_turn(checkpoint_id, scenario)


async def run() -> dict[str, Any]:
    global JOURNAL
    JOURNAL = RequestJournal(JOURNAL_PATH, "p0-sdk-a01-c1-live", 4, 2048)
    if JOURNAL.records():
        return {"candidate": CANDIDATE, "status": "existing_input_replay_blocked",
                "real_http": 0, "persisted_requests": len(JOURNAL.records())}
    admission.bootstrap()
    checkpoints.bootstrap()
    Gateway.prepare()
    DBOS(config=DBOSConfig(
        name="cloudhelm-p0-a01", system_database_url=DSN, dbos_system_schema="p0_a01_dbos",
        application_version="p0-a01-r1", executor_id="p0-a01-single-worker",
        enable_otlp=False, use_listen_notify=False, run_migrations=True,
        log_level="WARNING", console_log_level="WARNING",
    ))
    DBOS.launch()
    report: dict[str, Any] = {"candidate": CANDIDATE, "scenarios": {}}
    try:
        for scenario in ("normal", "disconnect"):
            scope = scope_for(scenario)
            admission.seed_scope(scope, Decimal("0.10"))
            checkpoint_id = checkpoints.put(ContextReferences(
                requirement_ref="reference-requirements-r1", input_set_ref=CANDIDATE,
                history_ref=f"history:a01:{scenario}:r1", artifact_ref="artifact:counter:r1",
                secret_resource_ref="resource:authorized-custom-provider",
            ))
            workflow_id = f"p0-a01-{scenario}-r1"
            with SetWorkflowID(workflow_id):
                handle = await DBOS.start_workflow_async(safe_agent_run, checkpoint_id, scenario)
            result = await handle.get_result()
            before = len(JOURNAL.records())
            with SetWorkflowID(workflow_id):
                replay = await DBOS.start_workflow_async(safe_agent_run, checkpoint_id, scenario)
            replay_result = await replay.get_result()
            assert replay_result == result and len(JOURNAL.records()) == before
            result["same_workflow_replay_real_http"] = 0
            report["scenarios"][scenario] = result
        report["real_http"] = len(JOURNAL.records())
        results = report["scenarios"]
        report["passed"] = all(
            item.get("result_reconciled") and item["facts"]["operations"] == 1
            and item["facts"]["effects"] == 1 and item["facts"]["counter"] == 1
            for item in results.values()
        ) and results["normal"]["outcome"] == "completed" and results["disconnect"]["outcome"] == "unknown"
        return report
    finally:
        DBOS.destroy()
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print("live_disabled; --live selects the fixed authorized 4-request input")
        raise SystemExit(0)
    LIVE_ENABLED = True
    try:
        report = asyncio.run(run())
        print(json.dumps(report, ensure_ascii=False, default=str, separators=(",", ":")))
        raise SystemExit(0 if report.get("passed") else 1)
    except Exception as exc:
        print(json.dumps({"candidate": CANDIDATE, "passed": False, "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
