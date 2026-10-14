"""Admitted new-request recovery workflow for the isolated P0.1 probe."""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from dbos import DBOS, DBOSClient, DBOSConfig, EnqueueOptions
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations.seam_admission import BudgetExceeded, ExecutionScope, GateDenied, SeamAdmission  # noqa: E402
from integrations.seam_checkpoint import CheckpointStore, ContextReferences  # noqa: E402
from integrations.seam_stream import MoneyGuardTransport  # noqa: E402
from scripts.p0.model_boundary import (  # noqa: E402
    AdmissionDenied, AdmissionTransport, JOURNAL_PATH, MODEL_NAME, RequestBudget,
    RequestJournal, SafeConfigurationError, _authorized_config, safe_status,
)

DSN = "postgresql+psycopg://cloudhelm_probe@127.0.0.1:55432/cloudhelm_p0"
SYSTEM_SCHEMA = "dbos_p0_admitted_recovery"
APP_NAME = "cloudhelm-p0-admitted-recovery"
APP_VERSION = "p0-a02-recovery-r1"
EXECUTOR_ID = "p0-a02-recovery-worker-r1"
QUEUE_NAME = "p0-a02-recovery-r1"
WORKFLOW_NAME = "p0.a02.admitted_recovery"
JOURNAL_BATCH = "p0-sdk-a02-recovery-r1"
MAX_REQUESTS = 1
MAX_RESERVED_OUTPUT_TOKENS = 512
CASES = ("allow", "cancel", "revoke", "budget")
BUSINESS_SCHEMA = "p0_admitted_recovery"
LIVE_ENABLED = False
engine = create_engine(DSN, pool_size=2, max_overflow=0, hide_parameters=True)
admission = SeamAdmission(engine)
checkpoints = CheckpointStore(engine)


def _case(case: str) -> str:
    if case not in CASES: raise ValueError("P0_A02_UNSUPPORTED_CASE")
    return case

def scope_for(case: str) -> ExecutionScope:
    prefix = f"a02-recovery-{_case(case)}"
    return ExecutionScope(prefix, f"{prefix}-session", f"{prefix}-run", "r1", "r1", "r1")

def bootstrap() -> None:
    with engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {BUSINESS_SCHEMA}"))
        connection.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {BUSINESS_SCHEMA}.barriers (
                case_name text PRIMARY KEY, attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
                released boolean NOT NULL DEFAULT false)
        """))
        for case in CASES:
            connection.execute(text(f"INSERT INTO {BUSINESS_SCHEMA}.barriers (case_name) "
                                    "VALUES (:case) ON CONFLICT (case_name) DO NOTHING"), {"case": case})
    admission.bootstrap(); checkpoints.bootstrap()

def seed_scope(case: str) -> ExecutionScope:
    scope = scope_for(case)
    admission.seed_scope(scope, Decimal("0.10"))
    return scope

def put_checkpoint(case: str) -> str:
    case = _case(case)
    refs = ContextReferences(requirement_ref="requirements:p0-a02-recovery-r1",
        input_set_ref="input-set:p0-a02-recovery-r1", history_ref=f"history:a02-recovery:{case}:r1",
        artifact_ref=f"artifact:a02-recovery:{case}:r1", secret_resource_ref="resource:authorized-custom-provider")
    return checkpoints.put(refs)

def _barrier(case: str, action: str) -> dict[str, int | bool]:
    statements = {
        "snapshot": f"SELECT attempts, released FROM {BUSINESS_SCHEMA}.barriers WHERE case_name=:case",
        "release": f"UPDATE {BUSINESS_SCHEMA}.barriers SET released=true WHERE case_name=:case RETURNING attempts,released",
        "attempt": f"UPDATE {BUSINESS_SCHEMA}.barriers SET attempts=attempts+1 WHERE case_name=:case RETURNING attempts,released",
    }
    context = engine.connect() if action == "snapshot" else engine.begin()
    with context as connection:
        row = connection.execute(text(statements[action]), {"case": _case(case)}).mappings().first()
    if row is None:
        raise RuntimeError("P0_A02_BARRIER_NOT_FOUND")
    return {"attempts": row["attempts"], "released": row["released"]}

def barrier_snapshot(case: str) -> dict[str, int | bool]: return _barrier(case, "snapshot")
def release_barrier(case: str) -> dict[str, int | bool]: return _barrier(case, "release")

def enqueue(client: DBOSClient, case: str, workflow_id: str, checkpoint_ref: str) -> str:
    options = EnqueueOptions(workflow_name=WORKFLOW_NAME, queue_name=QUEUE_NAME,
        workflow_id=workflow_id, workflow_id_reuse_policy="reject",
        app_version=APP_VERSION, application_name=APP_NAME)
    return client.enqueue(options, checkpoint_ref, _case(case)).get_workflow_id()

def workflow_status(client: DBOSClient, workflow_id: str) -> Any | None:
    rows = client.list_workflows(workflow_ids=[workflow_id], load_input=True, load_output=True, limit=1)
    return rows[0] if rows else None

def workflow_result(client: DBOSClient, workflow_id: str) -> Any:
    return client.retrieve_workflow(workflow_id).get_result(polling_interval_sec=0.05)


@DBOS.step(name="p0.a02.recovery_barrier")
def _wait_at_barrier(checkpoint_ref: str, case: str) -> dict[str, int | bool]:
    case = _case(case)
    checkpoints.get(checkpoint_ref)
    row = _barrier(case, "attempt")
    deadline = time.monotonic() + 60
    while not row["released"] and time.monotonic() < deadline:
        time.sleep(0.05)
        row = barrier_snapshot(case)
    if not row["released"]:
        raise TimeoutError("P0_A02_BARRIER_RELEASE_TIMEOUT")
    return {"attempts": row["attempts"], "released": True}


def _journal_batch(case: str) -> str:
    return JOURNAL_BATCH if case == "allow" else f"{JOURNAL_BATCH}-{case}"


def _denial_code(exc: BaseException) -> str:
    if isinstance(exc, BudgetExceeded):
        return "budget_exceeded"
    codes = {
        "scope identity or revision is stale": "stale_execution_scope",
        "Task cancellation is requested": "task_cancelled",
        "current permission denies ordinary progress": "permission_revoked",
    }
    return codes.get(str(exc), "admission_denied")


def _cause_of_type(exc: BaseException, types: tuple[type[BaseException], ...]) -> BaseException | None:
    pending, seen = [exc], set()
    while pending and len(seen) < 8:
        current = pending.pop(0)
        if id(current) in seen: continue
        if isinstance(current, types):
            return current
        seen.add(id(current))
        pending.extend(c for c in (current.__cause__, current.__context__) if c is not None)
    return None


async def _drain_events(_ctx: Any, events: Any) -> None:
    async for _event in events:
        pass


def _model_facts(outcome: str, case: str, budget: RequestBudget | None,
                 money: MoneyGuardTransport | None, journal_batch: str,
                 request_ref: str | None = None, **extra: Any) -> dict[str, Any]:
    records = budget.records if budget else []
    record = records[-1] if records else None
    request_ref = request_ref or (record.request_record_id if record else None)
    try:
        business = admission.query_request(request_ref) if request_ref else None
    except Exception:
        business = None
    evidence = money.evidence[0] if money and money.evidence else {}
    usage = record.vendor_usage if record else None
    has_usage = isinstance(usage, dict) and all(type(usage.get(k)) is int for k in
                                                  ("input_tokens", "output_tokens", "total_tokens"))
    completed = evidence.get("response_completed", 0)
    scope = scope_for(case)
    return {
        "outcome": outcome, "scope": asdict(scope),
        "real_http": money.sent if money else 0,
        "journal_reservations": len(records),
        "local_reservation_visible": bool(record and record.preflight_commit_visible),
        "business_preflight_visible": bool(money and money.sent),
        "journal_batch": journal_batch, "request_ref": request_ref,
        "http_status": record.http_status if record else None,
        "stream_complete": evidence.get("stream_finished") is True and completed == 1,
        "completed_events": completed, "usage_present": has_usage, "usage": usage if has_usage else None,
        "business_status": business.get("status") if business else None,
        "business_reservation_usd": business.get("reservation_usd") if business else None,
        "business_actual_cost_usd": business.get("actual_cost_usd") if business else None,
        **extra,
    }


async def _one_live_request(checkpoint_ref: str, case: str) -> dict[str, Any]:
    journal_batch = _journal_batch(case)
    budget: RequestBudget | None = None
    money: MoneyGuardTransport | None = None
    transport: AdmissionTransport | None = None
    request_ref: str | None = None
    try:
        config = _authorized_config()
        scope = scope_for(case)
        journal = RequestJournal(
            JOURNAL_PATH, journal_batch, MAX_REQUESTS, MAX_RESERVED_OUTPUT_TOKENS
        )
        budget = RequestBudget(journal)
        money = MoneyGuardTransport(budget, admission, scope)
        transport = AdmissionTransport(money, budget, live=True, expected_config=config)
        checkpoints.get(checkpoint_ref)
        async with AsyncOpenAI(
            api_key=config.credential,
            base_url=config.base_url,
            http_client=httpx.AsyncClient(transport=transport, timeout=45),
            max_retries=0,
        ) as client:
            model = OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
            agent = Agent(model, instructions="Respond with one short sentence.",
                model_settings={"max_tokens": MAX_RESERVED_OUTPUT_TOKENS,
                                "openai_reasoning_effort": "max", "openai_service_tier": "default"},
                retries=0)
            with transport.scenario(case, max_logical_calls=1, require_stream=True):
                await agent.run("Reply with one short sentence.", event_stream_handler=_drain_events)
        record = budget.records[-1] if budget.records else None
        request_ref = record.request_record_id if record else None
        evidence = money.evidence[0] if money.evidence else {}
        status = record.http_status if record else None
        completed_events = evidence.get("response_completed", 0)
        complete = evidence.get("stream_finished") is True and completed_events == 1
        facts = _model_facts(
            "accepted" if status == 200 and complete and record and record.vendor_usage else "incomplete",
            case, budget, money, journal_batch, request_ref,
        )
        if status != 200 or not complete or not facts["usage_present"]:
            facts["outcome"] = "incomplete"
        return facts
    except Exception as exc:
        denial = _cause_of_type(exc, (GateDenied, BudgetExceeded, AdmissionDenied))
        if denial:
            return _model_facts(
                "denied", case, budget, money, journal_batch,
                denial_type=type(denial).__name__, denial_code=_denial_code(denial),
            )
        config_error = _cause_of_type(exc, (SafeConfigurationError,))
        if config_error:
            return _model_facts("blocked", case, budget, money, journal_batch,
                                blocker_type=type(config_error).__name__)
        facts = _model_facts("unknown", case, budget, money, journal_batch,
                             http_status=safe_status(exc), error_type=type(exc).__name__)
        if facts["http_status"] is None:
            record = budget.records[-1] if budget and budget.records else None
            facts["http_status"] = record.http_status if record else None
        return facts


@DBOS.step(name="p0.a02.admitted_new_model_request")
def _admitted_model_request(checkpoint_ref: str, case: str) -> dict[str, Any]:
    if not LIVE_ENABLED:
        return _model_facts("blocked", _case(case), None, None, _journal_batch(case),
                            blocker_type="live_worker_flag_required")
    return asyncio.run(_one_live_request(checkpoint_ref, _case(case)))


@DBOS.workflow(name=WORKFLOW_NAME)
def admitted_recovery(checkpoint_id: str, case: str) -> dict[str, Any]:
    case = _case(case)
    barrier = _wait_at_barrier(checkpoint_id, case)
    model = _admitted_model_request(checkpoint_id, case)
    return {"case": case, "barrier": barrier, "model": model}


def run_worker(*, live: bool, lifetime_seconds: float = 180) -> None:
    global LIVE_ENABLED
    if not live or not 1 <= lifetime_seconds <= 180:
        raise RuntimeError("P0_A02_WORKER_REQUIRES_LIVE_FLAG_AND_BOUNDED_LIFETIME")
    LIVE_ENABLED = True
    config = DBOSConfig(name=APP_NAME, system_database_url=DSN, dbos_system_schema=SYSTEM_SCHEMA,
        application_version=APP_VERSION, executor_id=EXECUTOR_ID, run_migrations=True,
        enable_otlp=False, use_listen_notify=False, max_executor_threads=2,
        log_level="CRITICAL", console_log_level="CRITICAL")
    DBOS(config=config)
    DBOS.listen_queues([QUEUE_NAME])
    DBOS.launch()
    DBOS.register_queue(QUEUE_NAME, worker_concurrency=1, global_concurrency=1,
                        on_conflict="always_update")
    deadline = time.monotonic() + lifetime_seconds
    try:
        while time.monotonic() < deadline: time.sleep(0.25)
    finally:
        DBOS.destroy()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true"); parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.worker or not args.live:
        parser.error("worker mode requires both --worker and --live")
    run_worker(live=args.live); return 0


if __name__ == "__main__":
    raise SystemExit(main())
