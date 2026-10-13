#!/usr/bin/env python3
"""Exercise the isolated P0 Hub/Remote Agent execution seam on loopback only."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import rfc8785
from pydantic import BaseModel, ConfigDict, Field, model_validator


PROTOCOL = "cloudhelm.p0.experimental"
APPROVAL_REF = "p0-isolated-probe"
TIME_DOMAIN = "p0-local-monotonic-test-only"
MAX_ACCEPT_TO_START_NS = 5_000_000_000
MAX_TIME_UNCERTAINTY_NS = 2_000_000_000
LOCAL_BIND = "127.0.0.1"


class Refusal(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PlanRef(StrictModel):
    release_id: str = Field(min_length=1)
    release_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class EnvironmentRevisionRef(StrictModel):
    revision_id: str = Field(min_length=1)
    revision_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")


class TargetRef(StrictModel):
    target_id: str = Field(min_length=1)
    environment_revision: str = Field(min_length=1)


class ExecutorRef(StrictModel):
    executor_id: str = Field(min_length=1)


class PlanStep(StrictModel):
    step_id: str = Field(min_length=1)
    step_type: str = Field(min_length=1)
    input_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    depends_on: list[str]


class RemotePlan(StrictModel):
    protocol: str = Field(pattern=r"^cloudhelm\.p0\.experimental$")
    operation_id: str = Field(min_length=1, max_length=128)
    plan_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    release: PlanRef
    environment_config_revision: EnvironmentRevisionRef
    target: TargetRef
    executor: ExecutorRef
    generation: int = Field(ge=0)
    steps: list[PlanStep] = Field(min_length=1)

    @model_validator(mode="after")
    def check_digest_and_steps(self) -> "RemotePlan":
        step_ids: set[str] = set()
        for step in self.steps:
            if step.step_type != "p0_local_counter_probe":
                raise ValueError("this isolated runner only supports p0_local_counter_probe")
            if step.step_id in step_ids:
                raise ValueError("step_id values must be unique within a plan")
            if len(set(step.depends_on)) != len(step.depends_on):
                raise ValueError("depends_on values must be unique")
            if not set(step.depends_on) <= step_ids:
                raise ValueError("depends_on must reference earlier steps")
            step_ids.add(step.step_id)
        snapshot = self.model_dump(mode="json", exclude={"plan_digest"})
        if self.plan_digest != digest(snapshot):
            raise ValueError("plan_digest does not match the canonical fixed plan")
        return self


class Conflict(Refusal):
    pass


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def load_schema() -> dict[str, Any]:
    schema_path = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "p0" / "remote-plan.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    model_schema = RemotePlan.model_json_schema()
    if set(schema["properties"]) != set(model_schema["properties"]):
        raise AssertionError("remote-plan JSON Schema fields do not match the Pydantic probe model")
    if set(schema["required"]) != set(model_schema["required"]):
        raise AssertionError("remote-plan JSON Schema required fields do not match the Pydantic probe model")
    return schema


def validate_local_paths(database: str) -> None:
    temporary_root = Path(tempfile.gettempdir()).resolve()
    resolved = Path(database).resolve()
    if not resolved.is_relative_to(temporary_root):
        raise Refusal("P0 probe ledger must stay under the system temporary directory")


def validate_loopback_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname != LOCAL_BIND or parsed.username or parsed.password or parsed.path != "/p0/step-permit":
        raise Refusal("P0 probe permits must use the isolated HTTP loopback authority only")
    if parsed.port is None or not 1 <= parsed.port <= 65535:
        raise Refusal("P0 loopback authority requires an explicit local port")


def make_plan(operation_id: str, specs: list[tuple[str, int]], executor_id: str = "p0-remote-executor") -> dict[str, Any]:
    steps = []
    previous: list[str] = []
    for step_id, duration_ms in specs:
        steps.append(
            {
                "step_id": step_id,
                "step_type": "p0_local_counter_probe",
                "input_digest": digest({"step_id": step_id, "duration_ms": duration_ms, "scope": "local-counter-only"}),
                "depends_on": previous.copy(),
            }
        )
        previous.append(step_id)
    plan = {
        "protocol": PROTOCOL,
        "operation_id": operation_id,
        "release": {"release_id": "release-p0-fixed", "release_digest": digest({"fixture": "fixed-test-artifact"})},
        "environment_config_revision": {
            "revision_id": "envcfg-p0-fixed-r1",
            "revision_digest": digest({"fixture": "synthetic-reference-only"}),
        },
        "target": {"target_id": "loopback-probe-target", "environment_revision": "env-revision-p0-start"},
        "executor": {"executor_id": executor_id},
        "generation": 1,
        "steps": steps,
    }
    plan["plan_digest"] = digest(plan)
    RemotePlan.model_validate(plan)
    return plan


def open_ledger(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS operations (
            operation_id TEXT PRIMARY KEY,
            plan_digest TEXT NOT NULL,
            plan_json TEXT NOT NULL,
            state TEXT NOT NULL,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            physical_occupied INTEGER NOT NULL DEFAULT 0,
            updated_at_ns INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS steps (
            operation_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            input_digest TEXT NOT NULL,
            state TEXT NOT NULL,
            grant_id TEXT,
            grant_payload TEXT,
            grant_signature TEXT,
            grant_executor_incarnation TEXT,
            attempt_pid INTEGER,
            result_json TEXT,
            last_error TEXT,
            physical_occupied INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (operation_id, step_id)
        );
        CREATE TABLE IF NOT EXISTS audit (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL,
            step_id TEXT,
            event TEXT NOT NULL,
            detail_json TEXT NOT NULL,
            recorded_at_ns INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS counter (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            value INTEGER NOT NULL
        );
        INSERT OR IGNORE INTO counter(singleton, value) VALUES (1, 0);
        CREATE TABLE IF NOT EXISTS counter_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL,
            step_id TEXT NOT NULL,
            child_pid INTEGER NOT NULL,
            recorded_at_ns INTEGER NOT NULL
        );
        """
    )
    return conn


def audit(conn: sqlite3.Connection, operation_id: str, step_id: str | None, event: str, details: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO audit(operation_id, step_id, event, detail_json, recorded_at_ns) VALUES (?, ?, ?, ?, ?)",
        (operation_id, step_id, event, json.dumps(details, sort_keys=True), time.monotonic_ns()),
    )


def register_plan(conn: sqlite3.Connection, plan: dict[str, Any]) -> bool:
    parsed = RemotePlan.model_validate(plan)
    operation_id = parsed.operation_id
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute("SELECT plan_digest, state FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if existing:
            if existing["plan_digest"] != parsed.plan_digest:
                raise Conflict("same operation_id with a different plan_digest")
            conn.execute("COMMIT")
            return True
        conn.execute(
            "INSERT INTO operations(operation_id, plan_digest, plan_json, state, updated_at_ns) VALUES (?, ?, ?, 'pending', ?)",
            (operation_id, parsed.plan_digest, json.dumps(plan, sort_keys=True), time.monotonic_ns()),
        )
        for step in parsed.steps:
            conn.execute(
                "INSERT INTO steps(operation_id, step_id, input_digest, state) VALUES (?, ?, ?, 'pending')",
                (operation_id, step.step_id, step.input_digest),
            )
        audit(conn, operation_id, None, "plan_registered", {"plan_digest": parsed.plan_digest})
        conn.execute("COMMIT")
        return False
    except Exception:
        conn.execute("ROLLBACK")
        raise


def set_operation_state(conn: sqlite3.Connection, operation_id: str, state: str) -> None:
    conn.execute("UPDATE operations SET state=?, updated_at_ns=? WHERE operation_id=?", (state, time.monotonic_ns(), operation_id))


def get_counter(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT value FROM counter WHERE singleton=1").fetchone()[0])


def authorization_context(conn: sqlite3.Connection, plan: dict[str, Any], step: dict[str, Any]) -> tuple[dict[str, str], str]:
    predecessors: dict[str, str] = {}
    for predecessor_id in step["depends_on"]:
        predecessor = conn.execute(
            "SELECT state, result_json FROM steps WHERE operation_id=? AND step_id=?",
            (plan["operation_id"], predecessor_id),
        ).fetchone()
        if predecessor is None or predecessor["state"] != "completed" or not predecessor["result_json"]:
            raise Refusal("a predecessor result is not confirmed")
        predecessors[predecessor_id] = digest(json.loads(predecessor["result_json"]))
    completed = conn.execute(
        "SELECT step_id FROM steps WHERE operation_id=? AND state='completed' ORDER BY rowid",
        (plan["operation_id"],),
    ).fetchall()
    actual_state = {
        "target_id": plan["target"]["target_id"],
        "environment_revision": plan["target"]["environment_revision"],
        "completed_steps": [row[0] for row in completed],
        "counter": get_counter(conn),
    }
    return predecessors, digest(actual_state)


def make_permit_request(conn: sqlite3.Connection, plan: dict[str, Any], step: dict[str, Any], incarnation: str) -> dict[str, Any]:
    predecessor_results, actual_state_digest = authorization_context(conn, plan, step)
    return {
        "approval_ref": APPROVAL_REF,
        "operation_id": plan["operation_id"],
        "plan_digest": plan["plan_digest"],
        "step_id": step["step_id"],
        "input_digest": step["input_digest"],
        "executor_id": plan["executor"]["executor_id"],
        "executor_incarnation": incarnation,
        "generation": plan["generation"],
        "environment_revision": plan["target"]["environment_revision"],
        "predecessor_results": predecessor_results,
        "actual_state_digest": actual_state_digest,
    }


def query_operation(conn: sqlite3.Connection, operation_id: str) -> dict[str, Any]:
    operation = conn.execute("SELECT * FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
    if operation is None:
        raise Refusal("operation not found")
    steps = conn.execute(
        "SELECT step_id, input_digest, state, grant_id, grant_executor_incarnation, attempt_pid, result_json, last_error, physical_occupied FROM steps WHERE operation_id=? ORDER BY rowid",
        (operation_id,),
    ).fetchall()
    return {
        "operation_id": operation_id,
        "plan_digest": operation["plan_digest"],
        "state": operation["state"],
        "cancel_requested": bool(operation["cancel_requested"]),
        "physical_occupied": bool(operation["physical_occupied"]),
        "steps": [dict(row) for row in steps],
    }


def initialize_counter_db(path: str) -> None:
    conn = open_ledger(path)
    conn.close()


class EphemeralEd25519:
    def __init__(self, directory: Path, suffix: str):
        openssl = shutil_which("openssl")
        self.openssl = openssl
        self.private_key = directory / f"hub-{suffix}-private.pem"
        self.public_key = directory / f"hub-{suffix}-public.pem"
        self.message_file = directory / f"hub-{suffix}-message.bin"
        self.signature_file = directory / f"hub-{suffix}-signature.bin"
        subprocess.run([openssl, "genpkey", "-algorithm", "ED25519", "-out", str(self.private_key)], check=True, capture_output=True)
        os.chmod(self.private_key, 0o600)
        subprocess.run([openssl, "pkey", "-in", str(self.private_key), "-pubout", "-out", str(self.public_key)], check=True, capture_output=True)

    def sign(self, payload: dict[str, Any]) -> str:
        self.message_file.write_bytes(rfc8785.dumps(payload))
        result = subprocess.run(
            [self.openssl, "pkeyutl", "-sign", "-inkey", str(self.private_key), "-rawin", "-in", str(self.message_file)],
            check=True,
            capture_output=True,
        )
        return base64.b64encode(result.stdout).decode("ascii")

    @staticmethod
    def verify(public_key: str, payload: dict[str, Any], signature: str) -> bool:
        key_path = Path(public_key)
        message_file = key_path.with_suffix(".verify-message.bin")
        signature_file = key_path.with_suffix(".verify-signature.bin")
        message_file.write_bytes(rfc8785.dumps(payload))
        signature_file.write_bytes(base64.b64decode(signature, validate=True))
        try:
            result = subprocess.run(
                [shutil_which("openssl"), "pkeyutl", "-verify", "-pubin", "-inkey", str(key_path), "-rawin", "-in", str(message_file), "-sigfile", str(signature_file)],
                capture_output=True,
            )
            return result.returncode == 0
        finally:
            message_file.unlink(missing_ok=True)
            signature_file.unlink(missing_ok=True)


def shutil_which(command: str) -> str:
    from shutil import which

    found = which(command)
    if not found:
        raise SystemExit(f"BLOCKED: required executable {command!r} is unavailable")
    return found


class PermitAuthority:
    """Loopback Hub test fixture with one fixed local approval record."""

    def __init__(self, key_dir: Path, key_suffix: str, expired_operations: set[str] | None = None):
        self.keys = EphemeralEd25519(key_dir, key_suffix)
        self.hub_incarnation = str(uuid.uuid4())
        self.time_epoch = str(uuid.uuid4())
        self.approvals: dict[str, dict[str, Any]] = {}
        self.expired_operations = expired_operations or set()
        self.grants: list[dict[str, str]] = []
        self.grant_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def do_POST(self) -> None:
                if self.path != "/p0/step-permit":
                    self.send_error(404)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if size <= 0 or size > 16_384:
                        self.send_error(413)
                        return
                    request = json.loads(self.rfile.read(size).decode("utf-8"))
                    response = outer.issue(request)
                    self.send_response(200)
                except PermissionError:
                    response = {"error": "approval_or_identity_mismatch"}
                    self.send_response(403)
                except Exception:
                    response = {"error": "invalid_request"}
                    self.send_response(400)
                body = json.dumps(response, separators=(",", ":")).encode("utf-8")
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer((LOCAL_BIND, 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://{LOCAL_BIND}:{self.server.server_port}/p0/step-permit"
        self.thread = threading.Thread(target=self.server.serve_forever, name="p0-loopback-hub", daemon=True)
        self.thread.start()

    def approve(self, plan: dict[str, Any]) -> None:
        with self._lock:
            self.approvals[plan["operation_id"]] = plan

    def issue(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            plan = self.approvals.get(request.get("operation_id"))
            if plan is None or request.get("approval_ref") != APPROVAL_REF:
                raise PermissionError
            if request.get("plan_digest") != plan["plan_digest"]:
                raise PermissionError
            step = next((item for item in plan["steps"] if item["step_id"] == request.get("step_id")), None)
            if step is None or step["input_digest"] != request.get("input_digest"):
                raise PermissionError
            if request.get("executor_id") != plan["executor"]["executor_id"]:
                raise PermissionError
            if request.get("generation") != plan["generation"]:
                raise PermissionError
            if set(request.get("predecessor_results", {})) != set(step["depends_on"]):
                raise PermissionError
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", request.get("actual_state_digest", "")):
                raise PermissionError
            cache_key = (plan["operation_id"], step["step_id"], request["executor_incarnation"])
            cached = self.grant_cache.get(cache_key)
            current_request_digest = digest(request)
            if cached is not None:
                if cached["request_digest"] != current_request_digest:
                    raise PermissionError
                return cached["response"]
            now = time.monotonic_ns()
            expires = now + 30_000_000_000
            if plan["operation_id"] in self.expired_operations:
                expires = now
            claims = {
                "grant_id": "grant-" + str(uuid.uuid4()),
                "approval_ref": APPROVAL_REF,
                "operation_id": plan["operation_id"],
                "plan_digest": plan["plan_digest"],
                "step_id": step["step_id"],
                "input_digest": step["input_digest"],
                "executor_id": plan["executor"]["executor_id"],
                "executor_incarnation": request["executor_incarnation"],
                "hub_incarnation": self.hub_incarnation,
                "generation": plan["generation"],
                "environment_revision": plan["target"]["environment_revision"],
                "predecessor_results_digest": digest(request["predecessor_results"]),
                "actual_state_digest": request["actual_state_digest"],
                "time_domain": TIME_DOMAIN,
                "time_epoch": self.time_epoch,
                "issued_at_ns": now,
                "expires_at_ns": expires,
                "time_uncertainty_ns": 0,
                "accepted_window_ns": MAX_ACCEPT_TO_START_NS,
                "test_scope": "local-counter-only",
                "issued_approval": APPROVAL_REF,
            }
            signature = self.keys.sign(claims)
            self.grants.append({"operation_id": claims["operation_id"], "step_id": claims["step_id"], "grant_id": claims["grant_id"]})
            response = {"claims": claims, "signature": signature}
            self.grant_cache[cache_key] = {"request_digest": current_request_digest, "response": response}
            return response

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def validate_time(claims: dict[str, Any], now_ns: int, accepted_at_ns: int | None = None) -> None:
    uncertainty = claims["time_uncertainty_ns"]
    if uncertainty < 0 or uncertainty > MAX_TIME_UNCERTAINTY_NS:
        raise Refusal("permit time uncertainty is unavailable or exceeds the P0 test gate")
    if claims["time_domain"] != TIME_DOMAIN or not claims["time_epoch"]:
        raise Refusal("permit time domain or epoch is unsupported")
    if now_ns - uncertainty < claims["issued_at_ns"]:
        raise Refusal("permit is not yet valid within the claimed interval")
    if now_ns + uncertainty >= claims["expires_at_ns"]:
        raise Refusal("permit expiry boundary reached")
    if accepted_at_ns is not None and now_ns - accepted_at_ns + uncertainty > MAX_ACCEPT_TO_START_NS:
        raise Refusal("accepted permit exceeded the five-second start window")


def get_permit(url: str, request: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(request, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def persist_accepted_grant(conn: sqlite3.Connection, plan: dict[str, Any], step: dict[str, Any], incarnation: str, permit: dict[str, Any]) -> None:
    claims = permit["claims"]
    conn.execute("BEGIN IMMEDIATE")
    try:
        current = conn.execute("SELECT state FROM steps WHERE operation_id=? AND step_id=?", (plan["operation_id"], step["step_id"])).fetchone()
        if current["state"] not in {"pending", "waiting_authorization"}:
            raise Refusal(f"step is not eligible to accept a permit from state {current['state']}")
        conn.execute(
            "UPDATE steps SET state='permit_accepted', grant_id=?, grant_payload=?, grant_signature=?, grant_executor_incarnation=?, last_error=NULL WHERE operation_id=? AND step_id=?",
            (claims["grant_id"], json.dumps(claims, sort_keys=True), permit["signature"], incarnation, plan["operation_id"], step["step_id"]),
        )
        audit(conn, plan["operation_id"], step["step_id"], "permit_accepted", {"grant_id": claims["grant_id"], "executor_incarnation": incarnation})
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def invalidate_old_grants(conn: sqlite3.Connection, plan: dict[str, Any], incarnation: str) -> None:
    rows = conn.execute(
        "SELECT step_id, grant_id, grant_executor_incarnation FROM steps WHERE operation_id=? AND state='permit_accepted'",
        (plan["operation_id"],),
    ).fetchall()
    for row in rows:
        if row["grant_executor_incarnation"] != incarnation:
            conn.execute(
                "UPDATE steps SET state='pending', grant_id=NULL, grant_payload=NULL, grant_signature=NULL, grant_executor_incarnation=NULL, last_error='old permit invalidated by executor restart' WHERE operation_id=? AND step_id=?",
                (plan["operation_id"], row["step_id"]),
            )
            audit(conn, plan["operation_id"], row["step_id"], "old_grant_invalidated", {"grant_id": row["grant_id"]})


def mark_blocked(conn: sqlite3.Connection, operation_id: str, step_id: str, state: str, reason: str) -> None:
    conn.execute(
        "UPDATE steps SET state=?, last_error=? WHERE operation_id=? AND step_id=?",
        (state, reason, operation_id, step_id),
    )
    set_operation_state(conn, operation_id, state)
    audit(conn, operation_id, step_id, state, {"reason": reason})


def process_effect(db_path: str, operation_id: str, step_id: str, duration_ms: int) -> int:
    conn = open_ledger(db_path)
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("UPDATE counter SET value=value+1 WHERE singleton=1")
    conn.execute(
        "INSERT INTO counter_events(operation_id, step_id, child_pid, recorded_at_ns) VALUES (?, ?, ?, ?)",
        (operation_id, step_id, os.getpid(), time.monotonic_ns()),
    )
    conn.execute("COMMIT")
    conn.close()
    if duration_ms:
        time.sleep(duration_ms / 1000)
    return 0


def worker_main(args: argparse.Namespace) -> int:
    plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
    RemotePlan.model_validate(plan)
    conn = open_ledger(args.database)
    try:
        duplicate = register_plan(conn, plan)
    except Conflict as exc:
        print(json.dumps({"outcome": "conflict", "reason": str(exc)}))
        return 3
    incarnation = str(uuid.uuid4())
    invalidate_old_grants(conn, plan, incarnation)
    current = query_operation(conn, plan["operation_id"])
    if current["state"] in {"succeeded", "cancelled"}:
        print(json.dumps({"outcome": "existing", "operation_id": plan["operation_id"], "state": current["state"], "duplicate": duplicate}))
        return 0
    cancel_requested = False

    def request_cancel(_signum: int, _frame: Any) -> None:
        nonlocal cancel_requested
        cancel_requested = True
        conn.execute("UPDATE operations SET cancel_requested=1, updated_at_ns=? WHERE operation_id=?", (time.monotonic_ns(), plan["operation_id"]))
        audit(conn, plan["operation_id"], None, "cancel_requested", {"physical_occupancy_retained": True})

    signal.signal(signal.SIGINT, request_cancel)
    conn.execute("UPDATE operations SET state='running', updated_at_ns=? WHERE operation_id=?", (time.monotonic_ns(), plan["operation_id"]))
    for index, step in enumerate(plan["steps"]):
        row = conn.execute("SELECT * FROM steps WHERE operation_id=? AND step_id=?", (plan["operation_id"], step["step_id"])).fetchone()
        if row["state"] == "completed":
            continue
        if row["state"].startswith("blocked_") or row["state"] in {"failed", "needs_reconciliation"}:
            set_operation_state(conn, plan["operation_id"], row["state"])
            return 0
        if cancel_requested or conn.execute("SELECT cancel_requested FROM operations WHERE operation_id=?", (plan["operation_id"],)).fetchone()[0]:
            set_operation_state(conn, plan["operation_id"], "cancelled")
            audit(conn, plan["operation_id"], step["step_id"], "later_step_blocked_by_cancel", {})
            break
        if row["state"] in {"intent", "running", "unknown"}:
            mark_blocked(conn, plan["operation_id"], step["step_id"], "needs_reconciliation", "prior physical outcome is not confirmed")
            return 0
        if args.barrier_step == step["step_id"]:
            barrier = Path(args.barrier_dir)
            barrier.mkdir(parents=True, exist_ok=True)
            (barrier / "ready").write_text("ready", encoding="utf-8")
            deadline = time.monotonic() + 10
            while not (barrier / "resume").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not (barrier / "resume").exists():
                mark_blocked(conn, plan["operation_id"], step["step_id"], "waiting_authorization", "probe barrier timed out")
                return 0
        try:
            request = make_permit_request(conn, plan, step, incarnation)
        except Refusal as exc:
            mark_blocked(conn, plan["operation_id"], step["step_id"], "needs_reconciliation", str(exc))
            return 0
        try:
            permit = get_permit(args.authority_url, request)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            mark_blocked(conn, plan["operation_id"], step["step_id"], "waiting_authorization", "online permit unavailable")
            return 0
        claims = permit.get("claims", {})
        if not EphemeralEd25519.verify(args.public_key, claims, permit.get("signature", "")):
            mark_blocked(conn, plan["operation_id"], step["step_id"], "blocked_invalid_permit", "permit signature verification failed")
            return 0
        expected = {
            "approval_ref": APPROVAL_REF,
            "operation_id": plan["operation_id"],
            "plan_digest": plan["plan_digest"],
            "step_id": step["step_id"],
            "input_digest": step["input_digest"],
            "executor_id": plan["executor"]["executor_id"],
            "executor_incarnation": incarnation,
            "generation": plan["generation"],
            "environment_revision": plan["target"]["environment_revision"],
            "predecessor_results_digest": digest(request["predecessor_results"]),
            "actual_state_digest": request["actual_state_digest"],
            "test_scope": "local-counter-only",
        }
        if any(claims.get(key) != value for key, value in expected.items()):
            mark_blocked(conn, plan["operation_id"], step["step_id"], "blocked_permit_mismatch", "permit identity does not match the fixed plan")
            return 0
        received_at_ns = time.monotonic_ns()
        try:
            validate_time(claims, received_at_ns)
        except Refusal as exc:
            mark_blocked(conn, plan["operation_id"], step["step_id"], "blocked_expired", str(exc))
            return 0
        persist_accepted_grant(conn, plan, step, incarnation, permit)
        if args.pause_after_accept_step == step["step_id"]:
            conn.execute("UPDATE operations SET state='paused_after_accept' WHERE operation_id=?", (plan["operation_id"],))
            while True:
                time.sleep(60)
        if args.delay_after_accept_ms:
            time.sleep(args.delay_after_accept_ms / 1000)
        try:
            validate_time(claims, time.monotonic_ns(), received_at_ns)
        except Refusal as exc:
            mark_blocked(conn, plan["operation_id"], step["step_id"], "blocked_start_window", str(exc))
            return 0
        conn.execute(
            "UPDATE steps SET state='intent', physical_occupied=1 WHERE operation_id=? AND step_id=?",
            (plan["operation_id"], step["step_id"]),
        )
        conn.execute(
            "UPDATE operations SET physical_occupied=1, updated_at_ns=? WHERE operation_id=?",
            (time.monotonic_ns(), plan["operation_id"]),
        )
        audit(conn, plan["operation_id"], step["step_id"], "physical_intent_recorded", {"grant_id": claims["grant_id"]})
        duration_ms = args.effect_duration_ms if args.effect_duration_ms else duration_for_step(plan, step["step_id"])
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--local-seam", "--effect", "--database", args.database, "--operation-id", plan["operation_id"], "--step-id", step["step_id"], "--duration-ms", str(duration_ms)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=Path(args.database).resolve().parent,
        )
        conn.execute(
            "UPDATE steps SET state='running', attempt_pid=? WHERE operation_id=? AND step_id=?",
            (child.pid, plan["operation_id"], step["step_id"]),
        )
        audit(conn, plan["operation_id"], step["step_id"], "child_started", {"pid": child.pid})
        exit_code = child.wait()
        conn.execute(
            "UPDATE steps SET state=?, physical_occupied=0, result_json=? WHERE operation_id=? AND step_id=?",
            ("completed" if exit_code == 0 else "failed", json.dumps({"pid": child.pid, "exit_code": exit_code}), plan["operation_id"], step["step_id"]),
        )
        conn.execute("UPDATE operations SET physical_occupied=0, updated_at_ns=? WHERE operation_id=?", (time.monotonic_ns(), plan["operation_id"]))
        audit(conn, plan["operation_id"], step["step_id"], "child_stopped_confirmed", {"exit_code": exit_code})
        if exit_code != 0:
            set_operation_state(conn, plan["operation_id"], "failed")
            return 1
        if cancel_requested:
            set_operation_state(conn, plan["operation_id"], "cancelled")
            audit(conn, plan["operation_id"], None, "cancelled_after_child_stop", {"later_steps_blocked": True})
            break
        if index == len(plan["steps"]) - 1:
            set_operation_state(conn, plan["operation_id"], "succeeded")
        if args.drop_receipt_after_step == step["step_id"]:
            os._exit(77)
    current = query_operation(conn, plan["operation_id"])
    print(json.dumps({"outcome": current["state"], "operation_id": plan["operation_id"], "plan_digest": plan["plan_digest"], "counter": get_counter(conn)}))
    return 0


def duration_for_step(plan: dict[str, Any], step_id: str) -> int:
    # The isolated fixture binds its duration into the step digest and input contract.
    return int(plan.get("probe_durations_ms", {}).get(step_id, 0))


def effect_main(args: argparse.Namespace) -> int:
    return process_effect(args.database, args.operation_id, args.step_id, args.duration_ms)


def query_main(args: argparse.Namespace) -> int:
    conn = open_ledger(args.database)
    try:
        print(json.dumps(query_operation(conn, args.query_operation_id), sort_keys=True))
    finally:
        conn.close()
    return 0


def make_plan_file(directory: Path, plan: dict[str, Any], label: str) -> Path:
    path = directory / f"{label}.plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, sort_keys=True), encoding="utf-8", newline="\n")
    return path


def child_environment() -> dict[str, str]:
    openssl = shutil_which("openssl")
    env = {"PATH": str(Path(openssl).parent) + os.pathsep + "/usr/bin" + os.pathsep + "/bin", "LANG": "C.UTF-8", "PYTHONIOENCODING": "utf-8"}
    return env


def start_worker(plan_file: Path, database: Path, authority: PermitAuthority, extra: list[str] | None = None) -> subprocess.Popen:
    args = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--local-seam",
        "--worker",
        "--plan-file",
        str(plan_file),
        "--database",
        str(database),
        "--authority-url",
        authority.url,
        "--public-key",
        str(authority.keys.public_key),
    ]
    if extra:
        args.extend(extra)
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=child_environment(), cwd=database.parent)


def query_in_child(plan_file: Path, database: Path, operation_id: str) -> dict[str, Any]:
    del plan_file
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--local-seam", "--query", "--database", str(database), "--query-operation-id", operation_id],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=child_environment(),
        cwd=database.parent,
    )
    return json.loads(result.stdout)


def wait_for(database: Path, operation_id: str, predicate: Any, timeout: float = 8.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        conn = open_ledger(str(database))
        try:
            try:
                state = query_operation(conn, operation_id)
            except Refusal:
                state = None
        finally:
            conn.close()
        if state is not None and predicate(state):
            return state
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for operation {operation_id}")


def finish_worker(process: subprocess.Popen, expected: set[int] | None = None) -> tuple[int, str]:
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        _stdout, _stderr = process.communicate(timeout=2)
        raise AssertionError("Remote Agent probe worker exceeded its bounded wait and was stopped") from None
    allowed = expected or {0}
    if process.returncode not in allowed:
        detail = (stderr or "").strip()[-800:]
        raise AssertionError(f"Remote Agent probe worker failed with exit={process.returncode}: {detail or 'no diagnostic'}")
    return int(process.returncode), stdout


def counter_value(database: Path) -> int:
    conn = open_ledger(str(database))
    try:
        return get_counter(conn)
    finally:
        conn.close()


def create_plan_snapshot(plan: dict[str, Any], db: Path) -> None:
    make_plan_file(db.parent, plan, plan["operation_id"])


def test_exact_time_boundaries() -> None:
    claims = {
        "time_domain": TIME_DOMAIN,
        "time_epoch": "test-epoch",
        "issued_at_ns": 10_000,
        "expires_at_ns": 20_000,
        "time_uncertainty_ns": 0,
    }
    try:
        validate_time(claims, 20_000)
    except Refusal as exc:
        if "expiry boundary" not in str(exc):
            raise
    else:
        raise AssertionError("T + uncertainty == expires_at must be rejected")
    claims["expires_at_ns"] = 50_000_000_000
    claims["time_uncertainty_ns"] = 1
    try:
        validate_time(claims, claims["issued_at_ns"] + MAX_ACCEPT_TO_START_NS, claims["issued_at_ns"])
    except Refusal as exc:
        if "five-second" not in str(exc):
            raise
    else:
        raise AssertionError("an unaccounted time uncertainty at the five-second boundary must be rejected")


def wait_for_file(path: Path, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for isolated probe barrier {path.name}")


def run_probe() -> dict[str, Any]:
    started_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    load_schema()
    shutil_which("openssl")
    with tempfile.TemporaryDirectory(prefix="cloudhelm-p0-remote-") as temporary:
        root = Path(temporary)
        database = root / "remote-ledger.sqlite3"
        initialize_counter_db(str(database))
        assertions: list[str] = []
        grants_observed = 0
        fail_closed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=child_environment(),
            cwd=root,
        )
        if fail_closed.returncode != 2 or "BLOCKED" not in fail_closed.stdout:
            raise AssertionError("default invocation did not keep the product execution path blocked")
        assertions.append("default_entrypoint: blocked without explicit local-seam opt-in")

        # The loopback Hub returns the original grant for the same request identity and digest.
        grant_plan = make_plan("op-grant-retry", [("grant-step", 0)])
        create_plan_snapshot(grant_plan, database)
        grant_authority = PermitAuthority(root, "hub-grant-cache")
        grant_authority.approve(grant_plan)
        grant_conn = open_ledger(str(database))
        register_plan(grant_conn, grant_plan)
        grant_request = make_permit_request(grant_conn, grant_plan, grant_plan["steps"][0], "fixed-probe-executor-incarnation")
        original_permit = get_permit(grant_authority.url, grant_request)
        repeated_permit = get_permit(grant_authority.url, grant_request)
        changed_request = dict(grant_request, actual_state_digest=digest({"changed": True}))
        try:
            get_permit(grant_authority.url, changed_request)
        except urllib.error.HTTPError as exc:
            if exc.code != 403:
                raise
        else:
            raise AssertionError("same grant identity with a changed request digest was accepted")
        grant_conn.close()
        if original_permit["claims"]["grant_id"] != repeated_permit["claims"]["grant_id"] or len(grant_authority.grants) != 1:
            raise AssertionError("repeated grant request did not return its original grant")
        assertions.append("grant_redelivery: same digest queried the original grant; changed digest conflicted")
        grants_observed += len(grant_authority.grants)
        grant_authority.close()

        # A full fixed two-step plan proves one online permit per new step and fail-closed disconnect behavior.
        disconnect_plan = make_plan("op-disconnect", [("step-one", 120), ("step-two", 0)])
        create_plan_snapshot(disconnect_plan, database)
        authority = PermitAuthority(root, "hub-1")
        authority.approve(disconnect_plan)
        barrier = root / "between-steps"
        worker = start_worker(root / "op-disconnect.plan.json", database, authority, ["--barrier-step", "step-two", "--barrier-dir", str(barrier)])
        wait_for(database, "op-disconnect", lambda state: state["steps"][0]["state"] == "completed")
        wait_for_file(barrier / "ready")
        first_grant_count = len(authority.grants)
        authority.close()
        (barrier / "resume").write_text("resume", encoding="utf-8")
        finish_worker(worker)
        disconnected = query_in_child(root / "op-disconnect.plan.json", database, "op-disconnect")
        if disconnected["steps"][1]["state"] != "waiting_authorization" or counter_value(database) != 1:
            raise AssertionError(f"Hub disconnect did not block the next physical step: {disconnected}; counter={counter_value(database)}")
        assertions.append("disconnect_before_step_two: step-one=completed, step-two=waiting_authorization, counter=1")
        grants_observed += first_grant_count

        # Repeated delivery queries the same operation; a changed digest conflicts under the same identity.
        retry = start_worker(root / "op-disconnect.plan.json", database, authority)
        finish_worker(retry)
        if counter_value(database) != 1:
            raise AssertionError("duplicate plan delivery repeated a completed side effect")
        assertions.append("duplicate_delivery: original completed step was queried without a second child")
        changed = json.loads(json.dumps(disconnect_plan))
        changed["steps"][0]["input_digest"] = digest({"different": "same-operation"})
        changed["plan_digest"] = digest({key: value for key, value in changed.items() if key != "plan_digest"})
        changed_path = make_plan_file(root, changed, "same-op-different-digest")
        conflict_worker = start_worker(changed_path, database, authority)
        finish_worker(conflict_worker, {3})
        if counter_value(database) != 1:
            raise AssertionError("same identity with a different digest reached a side effect")
        assertions.append("same_operation_different_digest: conflict")

        # A connected plan advances both fixed steps, with a fresh current permit for each one.
        complete_plan = make_plan("op-two-step-complete", [("first-counter", 0), ("second-counter", 0)])
        complete_path = make_plan_file(root, complete_plan, "op-two-step-complete")
        complete_authority = PermitAuthority(root, "hub-complete")
        complete_authority.approve(complete_plan)
        before_complete = counter_value(database)
        complete_worker = start_worker(complete_path, database, complete_authority)
        finish_worker(complete_worker)
        complete_state = query_in_child(complete_path, database, "op-two-step-complete")
        if complete_state["state"] != "succeeded" or counter_value(database) != before_complete + 2 or len(complete_authority.grants) != 2:
            raise AssertionError("full plan did not require and record a current permit for each new step")
        assertions.append("complete_plan: two sequential child processes each followed a current online permit")
        grants_observed += len(complete_authority.grants)
        complete_authority.close()

        # The receipt is deliberately lost after a real subprocess effect; a fresh process queries the ledger.
        receipt_plan = make_plan("op-receipt-lost", [("counter-once", 0)])
        receipt_path = make_plan_file(root, receipt_plan, "op-receipt-lost")
        receipt_authority = PermitAuthority(root, "hub-3")
        receipt_authority.approve(receipt_plan)
        before_receipt = counter_value(database)
        receipt_worker = start_worker(receipt_path, database, receipt_authority, ["--drop-receipt-after-step", "counter-once"])
        finish_worker(receipt_worker, {77})
        recovered = query_in_child(receipt_path, database, "op-receipt-lost")
        if recovered["state"] != "succeeded" or counter_value(database) != before_receipt + 1:
            raise AssertionError("lost receipt could not be reconciled from the local durable ledger")
        receipt_retry = start_worker(receipt_path, database, receipt_authority)
        finish_worker(receipt_retry)
        if counter_value(database) != before_receipt + 1:
            raise AssertionError("receipt retry repeated the child side effect")
        assertions.append("lost_receipt: restarted query found success; replay did not increment counter")
        grants_observed += len(receipt_authority.grants)
        receipt_authority.close()

        # Cancellation leaves physical occupancy recorded until the actual child exits.
        cancel_plan = make_plan("op-cancel", [("slow-counter", 1700), ("must-not-run", 0)])
        cancel_path = make_plan_file(root, cancel_plan, "op-cancel")
        cancel_authority = PermitAuthority(root, "hub-4")
        cancel_authority.approve(cancel_plan)
        before_cancel = counter_value(database)
        cancel_worker = start_worker(cancel_path, database, cancel_authority, ["--effect-duration-ms", "1700"])
        running = wait_for(database, "op-cancel", lambda state: state["steps"][0]["state"] == "running")
        if not running["physical_occupied"]:
            raise AssertionError("running child did not retain physical occupancy")
        cancel_worker.send_signal(signal.SIGINT)
        time.sleep(0.08)
        during_cancel = query_in_child(cancel_path, database, "op-cancel")
        if not during_cancel["cancel_requested"] or not during_cancel["physical_occupied"]:
            raise AssertionError("cancel released physical occupancy before the child stopped")
        finish_worker(cancel_worker)
        after_cancel = query_in_child(cancel_path, database, "op-cancel")
        if after_cancel["state"] != "cancelled" or after_cancel["physical_occupied"] or after_cancel["steps"][1]["state"] != "pending":
            raise AssertionError("cancel did not stop later steps after physical confirmation")
        if counter_value(database) != before_cancel + 1:
            raise AssertionError("cancelled plan ran a later step")
        assertions.append("cancel: occupancy retained during child; released only after observed exit")
        grants_observed += len(cancel_authority.grants)
        cancel_authority.close()

        # Expired grants are fetched online, signature-checked, then refused before a child is created.
        expired_plan = make_plan("op-expired", [("expired-counter", 0)])
        expired_path = make_plan_file(root, expired_plan, "op-expired")
        expired_authority = PermitAuthority(root, "hub-5", {"op-expired"})
        expired_authority.approve(expired_plan)
        before_expired = counter_value(database)
        expired_worker = start_worker(expired_path, database, expired_authority)
        finish_worker(expired_worker)
        expired_state = query_in_child(expired_path, database, "op-expired")
        if expired_state["state"] != "blocked_expired" or counter_value(database) != before_expired:
            raise AssertionError("expired online permit was not rejected before the physical step")
        assertions.append("expired_permit: online signed grant rejected before child start")
        grants_observed += len(expired_authority.grants)
        expired_authority.close()

        # The accepted-to-start boundary is measured with an actual online grant; >5 seconds is blocked.
        window_plan = make_plan("op-start-window", [("late-counter", 0)])
        window_path = make_plan_file(root, window_plan, "op-start-window")
        window_authority = PermitAuthority(root, "hub-6")
        window_authority.approve(window_plan)
        before_window = counter_value(database)
        window_worker = start_worker(window_path, database, window_authority, ["--delay-after-accept-ms", "5001"])
        finish_worker(window_worker)
        window_state = query_in_child(window_path, database, "op-start-window")
        if window_state["state"] != "blocked_start_window" or counter_value(database) != before_window:
            raise AssertionError("permit accepted-to-start delay over five seconds was not rejected")
        assertions.append("accepted_to_start: 5.001s refused; counter unchanged")
        grants_observed += len(window_authority.grants)
        window_authority.close()
        test_exact_time_boundaries()
        assertions.append("time_boundaries: expires equality and five-second uncertainty edge refused")

        # Persist an accepted grant, restart both sides, rotate signing key/epoch, and require a new grant.
        restart_plan = make_plan("op-restart-old-grant", [("restart-counter", 0)])
        restart_path = make_plan_file(root, restart_plan, "op-restart-old-grant")
        old_authority = PermitAuthority(root, "hub-old")
        old_authority.approve(restart_plan)
        pause_worker = start_worker(restart_path, database, old_authority, ["--pause-after-accept-step", "restart-counter"])
        wait_for(database, "op-restart-old-grant", lambda state: state["steps"][0]["state"] == "permit_accepted")
        old_row = query_step_row(database, "op-restart-old-grant", "restart-counter")
        old_claims = json.loads(old_row["grant_payload"])
        old_signature = old_row["grant_signature"]
        old_grant_id = old_row["grant_id"]
        pause_worker.kill()
        finish_worker(pause_worker, {-signal.SIGKILL})
        old_authority.close()
        new_authority = PermitAuthority(root, "hub-new")
        new_authority.approve(restart_plan)
        if EphemeralEd25519.verify(str(new_authority.keys.public_key), old_claims, old_signature):
            raise AssertionError("old permit remained verifiable after Hub authority restart")
        before_restart = counter_value(database)
        restarted_worker = start_worker(restart_path, database, new_authority)
        finish_worker(restarted_worker)
        restart_state = query_in_child(restart_path, database, "op-restart-old-grant")
        new_row = query_step_row(database, "op-restart-old-grant", "restart-counter")
        audit_events = query_audit_events(database, "op-restart-old-grant")
        if restart_state["state"] != "succeeded" or new_row["grant_id"] == old_grant_id or counter_value(database) != before_restart + 1:
            raise AssertionError("restart reused an old permit or failed to obtain a current one")
        if "old_grant_invalidated" not in audit_events:
            raise AssertionError("restart did not persist old-grant invalidation evidence")
        assertions.append("restart: old executor grant invalidated; new Hub epoch/key and current grant required")
        grants_observed += len(new_authority.grants)
        new_authority.close()

        # Query with a new process proves the durable ledger survived process restarts.
        final = query_in_child(restart_path, database, "op-restart-old-grant")
        return {
            "started_at_utc": started_at_utc,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "mode": "local-seam",
            "protocol": PROTOCOL,
            "authority": "loopback test fixture; fixed approval p0-isolated-probe",
            "signatures": "ephemeral Ed25519; private material stayed in temp memory/files and was not emitted",
            "time": "same-host monotonic test samples; no real clock-error bound claimed",
            "remote_topology": "Hub fixture and Remote Agent ran on the same WSL host; no independent machine or TLS claim",
            "counter_final": counter_value(database),
            "online_grants_issued": grants_observed,
            "restart_final_state": final["state"],
            "observations": assertions,
        }


def query_step_row(database: Path, operation_id: str, step_id: str) -> sqlite3.Row:
    conn = open_ledger(str(database))
    try:
        row = conn.execute("SELECT * FROM steps WHERE operation_id=? AND step_id=?", (operation_id, step_id)).fetchone()
        if row is None:
            raise AssertionError("expected step row was not persisted")
        return row
    finally:
        conn.close()


def query_audit_events(database: Path, operation_id: str) -> set[str]:
    conn = open_ledger(str(database))
    try:
        return {row[0] for row in conn.execute("SELECT event FROM audit WHERE operation_id=?", (operation_id,))}
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-seam", action="store_true", help="explicitly authorize the temporary loopback P0 probe")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--worker", action="store_true")
    modes.add_argument("--effect", action="store_true")
    modes.add_argument("--query", action="store_true")
    parser.add_argument("--plan-file")
    parser.add_argument("--database")
    parser.add_argument("--authority-url")
    parser.add_argument("--public-key")
    parser.add_argument("--query-operation-id")
    parser.add_argument("--duration-ms", type=int, default=0)
    parser.add_argument("--operation-id")
    parser.add_argument("--step-id")
    parser.add_argument("--barrier-step")
    parser.add_argument("--barrier-dir")
    parser.add_argument("--pause-after-accept-step")
    parser.add_argument("--delay-after-accept-ms", type=int, default=0)
    parser.add_argument("--drop-receipt-after-step")
    parser.add_argument("--effect-duration-ms", type=int)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.local_seam:
        print("BLOCKED: pass --local-seam to run only the temporary loopback counter probe; no production authorization path exists here")
        return 2
    if args.worker:
        required = (args.plan_file, args.database, args.authority_url, args.public_key)
        if not all(required):
            raise SystemExit("worker mode requires plan, ledger, loopback authority URL, and public verification key")
        validate_local_paths(args.database)
        validate_loopback_url(args.authority_url)
        if args.delay_after_accept_ms < 0 or args.delay_after_accept_ms > 6_000:
            raise SystemExit("isolated start-window delay must be between 0 and 6000 ms")
        if args.effect_duration_ms is not None and not 0 <= args.effect_duration_ms <= 5_000:
            raise SystemExit("isolated counter child duration must be between 0 and 5000 ms")
        return worker_main(args)
    if args.effect:
        if not args.database or not args.operation_id or not args.step_id:
            raise SystemExit("effect mode requires a ledger, operation_id, and step_id")
        validate_local_paths(args.database)
        if not 0 <= args.duration_ms <= 5_000:
            raise SystemExit("isolated counter child duration must be between 0 and 5000 ms")
        return effect_main(args)
    if args.query:
        if not args.database or not args.query_operation_id:
            raise SystemExit("query mode requires a ledger and operation_id")
        validate_local_paths(args.database)
        return query_main(args)
    print(json.dumps(run_probe(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
