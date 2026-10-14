"""P0.1-A02a2 fixed orchestration for admitted new-request recovery."""

from __future__ import annotations

import argparse, hashlib, importlib.metadata, json, os, signal, sqlite3, subprocess, sys, time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dbos import DBOS, DBOSClient
from sqlalchemy.engine import make_url

from integrations.model_pricing import calculate_reservation_upper_bound
from scripts.p0 import admitted_recovery_workflows as admitted
from scripts.p0.model_boundary import JOURNAL_PATH

CASES = ("cancel", "revoke", "budget", "allow")
DENIED = frozenset({"cancel", "revoke", "budget"})
WORKFLOW_IDS = {case: f"p0-a02-recovery-{case}-r1" for case in CASES}
HOLD_ID = "p0-a02-recovery-budget-unknown-r1"
HOLD_DIGEST = hashlib.sha256(HOLD_ID.encode("utf-8")).hexdigest()
HOLD_INPUT, HOLD_OUTPUT = 16_000, 128_000  # frozen global rates reserve exactly $0.10
WAIT_SECONDS = 90
ACTIVE_STAGE = "preflight"
LIVE_REPORT: dict[str, Any] | None = None


class ProbeFailure(RuntimeError):
    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(stage)


def _need(ok: bool, stage: str) -> None:
    if not ok:
        raise ProbeFailure(stage)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _journal_snapshot() -> dict[str, list[dict[str, Any]]]:
    """Read the fixed A02 sub-batches without creating or changing the journal."""
    rows_by_case = {case: [] for case in CASES}
    if not JOURNAL_PATH.exists():
        return rows_by_case
    try:
        with sqlite3.connect(JOURNAL_PATH.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not tables:
                return rows_by_case
            _need({"probe_batches", "request_records", "request_results"}.issubset(tables), "journal_schema")
            query = """SELECT latest.http_status, latest.vendor_usage_json FROM request_records r
                LEFT JOIN request_results latest ON latest.result_id=(SELECT MAX(result_id)
                    FROM request_results WHERE request_record_id=r.request_record_id)
                WHERE r.probe_key=? ORDER BY r.created_utc,r.request_record_id"""
            for case in CASES:
                key = admitted.JOURNAL_BATCH if case == "allow" else f"{admitted.JOURNAL_BATCH}-{case}"
                rows = db.execute(query, (key,)).fetchall()
                rows_by_case[case] = [{"http_status": r[0], "usage_present": r[1] is not None} for r in rows]
        return rows_by_case
    except ProbeFailure:
        raise
    except Exception:
        raise ProbeFailure("journal_read") from None


def _validate_dsn() -> None:
    try:
        url = make_url(admitted.DSN)
        valid = (url.drivername == "postgresql+psycopg" and url.host == "127.0.0.1"
                 and url.port == 55432 and url.database == "cloudhelm_p0"
                 and url.username == "cloudhelm_probe" and url.password is None)
    except Exception:
        valid = False
    _need(valid, "isolated_database_target")


def _client() -> DBOSClient:
    return DBOSClient(system_database_url=admitted.DSN, dbos_system_schema=admitted.SYSTEM_SCHEMA,
                      system_database_pool_size=4, system_database_polling_concurrency=1,
                      use_listen_notify=False, application_name=admitted.APP_NAME)


def _wait(predicate: Callable[[], Any], stage: str) -> Any:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if value := predicate():
            return value
        time.sleep(0.1)
    raise ProbeFailure(stage)


def _start_worker() -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        [sys.executable, str(Path(admitted.__file__).resolve()), "--worker", "--live"],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)
    if process.poll() is not None:
        raise ProbeFailure("worker_start")
    return process


def _stop_worker(process: subprocess.Popen[bytes], *, kill: bool) -> int:
    if process.poll() is None:
        process.kill() if kill else process.send_signal(signal.SIGTERM)
    try:
        return process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=5)


def _seed_hold(case: str) -> None:
    bound = calculate_reservation_upper_bound(
        model="gpt-6-luna", service_tier="standard", processing_mode="global",
        input_tokens_upper_bound=HOLD_INPUT, max_output_tokens=HOLD_OUTPUT,
        other_charges_upper_bound_usd=Decimal("0"),
        other_charges_basis="custom function tools only; no billed OpenAI hosted tools",
    )["reservation_upper_bound_usd"]
    _need(bound == Decimal("0.10"), "unknown_hold_fixed_bound")
    ledger = admitted.admission
    reserved = ledger.reserve_request(admitted.scope_for(case), HOLD_ID, HOLD_DIGEST, HOLD_INPUT, HOLD_OUTPUT)
    _need(reserved.get("should_send") is True, "unknown_hold_reservation")
    saved, observed = ledger.record_result(HOLD_ID, None), ledger.query_request(HOLD_ID)
    _need(saved.get("status") == "unknown" and observed and observed.get("status") == "unknown",
          "unknown_hold_not_retained")


def _run_case(client: DBOSClient, case: str, report: dict[str, Any]) -> None:
    global ACTIVE_STAGE
    wid = WORKFLOW_IDS[case]
    ACTIVE_STAGE = f"prepare_{case}"
    admitted.seed_scope(case)  # fixed $0.10 budget
    checkpoint = admitted.put_checkpoint(case)
    if case == "budget":
        _seed_hold(case)
    worker: subprocess.Popen[bytes] | None = _start_worker()
    first_pid, recovery_pid, killed_code = worker.pid, None, None
    authority_change: dict[str, Any] = {}
    try:
        ACTIVE_STAGE = f"enqueue_{case}"
        admitted.enqueue(client, case, wid, checkpoint)
        _wait(lambda: (b := admitted.barrier_snapshot(case)).get("attempts") == 1
              and not b.get("released") and (s := admitted.workflow_status(client, wid)) is not None
              and s.status == "PENDING", f"first_barrier_{case}")

        ACTIVE_STAGE = f"kill_worker_{case}"
        _need(os.name == "posix" and hasattr(signal, "SIGKILL"), "sigkill_requires_posix")
        killed_code, worker = _stop_worker(worker, kill=True), None
        _need(killed_code == -signal.SIGKILL, f"worker_not_sigkilled_{case}")
        state = admitted.workflow_status(client, wid)
        _need(state is not None and state.status == "PENDING", f"workflow_not_pending_{case}")

        ACTIVE_STAGE = f"mutate_gate_{case}"
        if case in {"cancel", "revoke"}:
            field, value = (("cancel_requested", True) if case == "cancel" else ("permitted", False))
            scope = admitted.scope_for(case)
            updated = admitted.admission.change_scope(scope, **{field: value})
            revision = "control_revision" if case == "cancel" else "permission_revision"
            advanced = getattr(updated, revision) != getattr(scope, revision)
            _need(advanced, f"authority_revision_{case}")
            authority_change = {field: value, f"{revision}_advanced": advanced}
        elif case == "budget":
            hold = admitted.admission.query_request(HOLD_ID)
            _need(hold is not None and hold.get("status") == "unknown", "unknown_hold_before_resume")
            authority_change = {"unknown_reservation_retained": True}

        ACTIVE_STAGE = f"restart_worker_{case}"
        worker = _start_worker()
        recovery_pid = worker.pid
        _need(recovery_pid != first_pid, f"worker_process_not_replaced_{case}")
        _wait(lambda: admitted.barrier_snapshot(case).get("attempts") == 2, f"recovery_attempt_{case}")
        state = admitted.workflow_status(client, wid)
        _need(state is not None and state.executor_id == admitted.EXECUTOR_ID, f"executor_identity_{case}")

        ACTIVE_STAGE = f"release_barrier_{case}"
        admitted.release_barrier(case)
        _wait(lambda: (s := admitted.workflow_status(client, wid)) is not None and
              s.status in {"SUCCESS", "ERROR", "CANCELLED", "MAX_RECOVERY_ATTEMPTS_EXCEEDED"},
              f"terminal_status_{case}")
        state = admitted.workflow_status(client, wid)
        _need(state is not None and state.status == "SUCCESS", f"workflow_success_{case}")

        ACTIVE_STAGE = f"verify_{case}"
        before = _journal_snapshot()[case]
        result = admitted.workflow_result(client, wid)
        replay = admitted.workflow_result(client, wid)
        after = _journal_snapshot()[case]
        _need(result == replay and before == after, f"completed_result_retrieval_{case}")
        model, allowed = result["model"], case == "allow"
        responses = sum(r["http_status"] is not None for r in after)
        _need(result.get("case") == case and result.get("barrier") == {"attempts": 2, "released": True},
              f"recovery_result_{case}")
        _need(len(after) == model.get("journal_reservations") == 1 and model.get("real_http") == responses,
              f"request_counts_{case}")
        _need(model.get("local_reservation_visible") is True, f"local_preflight_{case}")
        if allowed:
            _need(model.get("outcome") == "accepted" and model.get("http_status") == 200
                  and responses == 1 and after[0]["http_status"] == 200, "allow_http_200")
            _need(model.get("usage_present") is True and after[0]["usage_present"], "allow_usage")
            _need(model.get("stream_complete") is True and model.get("completed_events") == 1,
                  "allow_completed_stream")
            _need(model.get("business_preflight_visible") is True
                  and model.get("business_status") == "settled", "allow_business_ledger")
        else:
            _need(model.get("outcome") == "denied" and model.get("real_http") == responses == 0
                  and after[0]["http_status"] is None, f"deny_http_zero_{case}")
            _need(model.get("denial_type") in {"GateDenied", "BudgetExceeded", "AdmissionDenied"},
                  f"deny_reason_{case}")
            _need(model.get("business_preflight_visible") is False, f"deny_business_reservation_{case}")
        if case == "budget":
            hold = admitted.admission.query_request(HOLD_ID)
            _need(hold is not None and hold.get("status") == "unknown", "unknown_hold_after_resume")
            report["unknown_budget_hold"] = {"status": hold["status"], "reservation_usd": hold["reservation_usd"]}
        report["scenarios"][case] = {
            "workflow_id": wid, "status": state.status, "executor_id": state.executor_id,
            "worker_process_ids": [first_pid, recovery_pid], "sigkill_return_code": killed_code,
            "recovery_attempts": result["barrier"]["attempts"], "authority_change": authority_change,
            "outcome": model["outcome"], "denial_type": model.get("denial_type"),
            "denial_code": model.get("denial_code"),
            "local_journal_attempts": len(after), "actual_http_requests": model.get("real_http"),
            "http_status": model.get("http_status"), "usage_present": model.get("usage_present"),
            "usage": model.get("usage"),
            "stream_complete": model.get("stream_complete"),
            "completed_result_retrieval_no_new_request": True,
        }
    finally:
        if worker is not None:
            _stop_worker(worker, kill=False)


def _base_report() -> dict[str, Any]:
    return {
        "candidate": "P0.1-A02a2", "started_utc": _now(), "passed": False,
        "sdk_versions": {"dbos": _version("dbos"), "pydantic_ai": _version("pydantic-ai-slim")},
        "application_name": admitted.APP_NAME, "application_version": admitted.APP_VERSION,
        "system_schema": admitted.SYSTEM_SCHEMA, "executor_id": admitted.EXECUTOR_ID,
        "local_journal_attempts": 0, "actual_http_requests": 0, "scenarios": {},
    }


def _run_live(report: dict[str, Any]) -> dict[str, Any]:
    global ACTIVE_STAGE, LIVE_REPORT
    LIVE_REPORT = report
    _need(os.name == "posix", "sigkill_requires_posix")
    _validate_dsn()
    _need(not any(_journal_snapshot().values()), "existing_journal_requests_block_replay")
    ACTIVE_STAGE = "bootstrap"
    admitted.bootstrap()
    ACTIVE_STAGE = "dbos_system_migration"
    DBOS.migrate(admitted.DSN, schema=admitted.SYSTEM_SCHEMA)
    ACTIVE_STAGE = "dbos_client"
    client = _client()
    try:
        existing = [case for case, wid in WORKFLOW_IDS.items()
                    if admitted.workflow_status(client, wid) is not None]
        _need(not existing, "fixed_workflow_history_exists")
        for case in CASES:
            ACTIVE_STAGE = f"case_{case}"
            _run_case(client, case, report)
        snapshot = _journal_snapshot()
        report["local_journal_attempts"] = sum(map(len, snapshot.values()))
        report["actual_http_requests"] = sum(r["http_status"] is not None
                                              for rows in snapshot.values() for r in rows)
        report["passed"] = (report["local_journal_attempts"] == 4 and report["actual_http_requests"] == 1
                            and all(report["scenarios"][c]["outcome"] == "denied" for c in DENIED)
                            and report["scenarios"]["allow"]["outcome"] == "accepted")
        return report
    finally:
        client.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="run the fixed authorized recovery probe")
    if not (args := parser.parse_args()).live:
        print(json.dumps({"candidate": "P0.1-A02a2", "live_enabled": False}, sort_keys=True))
        return 0
    global LIVE_REPORT
    LIVE_REPORT = _base_report()
    try:
        report = _run_live(LIVE_REPORT)
        report["finished_utc"] = _now()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0 if report["passed"] else 1
    except Exception as exc:
        report = LIVE_REPORT or _base_report()
        report.update(passed=False, finished_utc=_now(),
                      failure={"stage": ACTIVE_STAGE, "type": type(exc).__name__})
        try:
            snapshot = _journal_snapshot()
            report["local_journal_attempts"] = sum(map(len, snapshot.values()))
            report["http_responses_observed"] = sum(r["http_status"] is not None
                                                     for rows in snapshot.values() for r in rows)
        except Exception:
            report["journal_counts"] = "unavailable"
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
