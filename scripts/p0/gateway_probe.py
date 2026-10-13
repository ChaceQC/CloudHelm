"""Bounded PostgreSQL-backed Gateway probe for P0 SDK seams.

This module is an isolated probe, not a product Gateway or operation scheduler.
Every probe business read/write goes through Gateway methods. The only direct SQL
outside Gateway is isolated schema bootstrap and reset of this fixed probe scope.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

import psycopg
from psycopg.types.json import Jsonb

SCHEMA = "p0_protocol"
DEFAULT_PROBE_ID = "sdk03-04-fixed-input-v1"
MAX_OPERATIONS_PER_PROBE = 8
POSTGRES_PARAMETERS = {
    "host": "127.0.0.1",
    "port": 55432,
    "dbname": "cloudhelm_p0",
    "user": "cloudhelm_probe",
    "connect_timeout": 3,
    "application_name": "cloudhelm-p0-sdk03-04-probe",
}


class GatewayProbeError(RuntimeError):
    """Base failure for this isolated probe."""


class GateDenied(GatewayProbeError):
    """The current policy denied or invalidated the request."""


class IdempotencyConflict(GatewayProbeError):
    """A stable operation identity was reused with a different input."""


class ResultConflict(GatewayProbeError):
    """A completed operation received a different result under the same identity."""


class ProbeCapacityExceeded(GatewayProbeError):
    """The fixed, bounded probe input exceeded its operation allowance."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_digest(tool_name: str, args: Mapping[str, Any]) -> str:
    normalized = {"tool_name": tool_name, "args": dict(args)}
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


def operation_identity(probe_id: str, idempotency_key: str) -> str:
    if not idempotency_key or len(idempotency_key) > 120:
        raise ValueError("idempotency_key must contain 1 to 120 characters")
    stable_input = f"cloudhelm-p0-probe\0{probe_id}\0{idempotency_key}"
    return "op_" + hashlib.sha256(stable_input.encode("utf-8")).hexdigest()[:32]


@dataclass
class CurrentGate:
    """Small mutable policy fixture so stale and revoked requests can be injected."""

    revision: str = "p0-gate-r1"
    allowed_tools: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {"query_counter", "submit_operation", "complete_operation", "await_operation"}
        )
    )

    def replace(self, *, revision: str, allowed_tools: set[str]) -> None:
        self.revision = revision
        self.allowed_tools = frozenset(allowed_tools)

    def decision(self, tool_name: str, supplied_revision: str) -> tuple[bool, str]:
        if supplied_revision != self.revision:
            return False, "stale_policy_revision"
        if tool_name not in self.allowed_tools:
            return False, "tool_not_allowed_by_current_policy"
        return True, "allowed"


class Gateway:
    """Probe Gateway with current-policy checks, stable identity and queryable effects."""

    def __init__(
        self,
        probe_id: str = DEFAULT_PROBE_ID,
        gate: CurrentGate | None = None,
    ) -> None:
        self.probe_id = probe_id
        self.gate = gate or CurrentGate()

    @staticmethod
    def prepare() -> str:
        """Create only the dedicated probe schema; return a non-secret server version."""
        try:
            with psycopg.connect(**POSTGRES_PARAMETERS) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("CREATE SCHEMA IF NOT EXISTS p0_protocol")
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS p0_protocol.operations (
                            probe_id text NOT NULL,
                            operation_id text NOT NULL,
                            idempotency_key text NOT NULL,
                            request_digest char(64) NOT NULL,
                            tool_name text NOT NULL,
                            status text NOT NULL
                                CHECK (status IN ('accepted', 'completed')),
                            receipt jsonb NOT NULL,
                            result_id text,
                            result_digest char(64),
                            final_result jsonb,
                            PRIMARY KEY (probe_id, operation_id),
                            UNIQUE (probe_id, idempotency_key)
                        )
                        """
                    )
                    cursor.execute(
                        """
                        ALTER TABLE p0_protocol.operations
                        ADD COLUMN IF NOT EXISTS result_digest char(64)
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS p0_protocol.effects (
                            probe_id text NOT NULL,
                            operation_id text NOT NULL,
                            effect_number integer NOT NULL,
                            effect_value integer NOT NULL,
                            PRIMARY KEY (probe_id, operation_id),
                            FOREIGN KEY (probe_id, operation_id)
                                REFERENCES p0_protocol.operations (probe_id, operation_id)
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS p0_protocol.counters (
                            probe_id text PRIMARY KEY,
                            value integer NOT NULL CHECK (value >= 0)
                        )
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS p0_protocol.gate_checks (
                            probe_id text NOT NULL,
                            check_id text NOT NULL,
                            tool_name text NOT NULL,
                            operation_id text,
                            supplied_revision text NOT NULL,
                            current_revision text NOT NULL,
                            allowed boolean NOT NULL,
                            reason text NOT NULL,
                            PRIMARY KEY (probe_id, check_id)
                        )
                        """
                    )
                    cursor.execute("SELECT current_setting('server_version')")
                    version = cursor.fetchone()[0]
            return version
        except psycopg.Error as exc:
            raise GatewayProbeError(
                "isolated PostgreSQL is unavailable; connection details are suppressed"
            ) from None

    def reset_scope(self) -> None:
        """Clear only this probe_id's disposable fixture rows before each run."""
        try:
            with psycopg.connect(**POSTGRES_PARAMETERS) as connection:
                with connection.transaction():
                    connection.execute(
                        "DELETE FROM p0_protocol.effects WHERE probe_id = %s",
                        (self.probe_id,),
                    )
                    connection.execute(
                        "DELETE FROM p0_protocol.operations WHERE probe_id = %s",
                        (self.probe_id,),
                    )
                    connection.execute(
                        "DELETE FROM p0_protocol.counters WHERE probe_id = %s",
                        (self.probe_id,),
                    )
                    connection.execute(
                        "DELETE FROM p0_protocol.gate_checks WHERE probe_id = %s",
                        (self.probe_id,),
                    )
        except psycopg.Error as exc:
            raise GatewayProbeError(
                "could not reset the dedicated probe scope; details are suppressed"
            ) from None

    @contextmanager
    def _authorized_transaction(
        self,
        tool_name: str,
        operation_id: str | None,
        supplied_revision: str,
    ) -> Iterator[psycopg.Connection[Any]]:
        allowed, reason = self.gate.decision(tool_name, supplied_revision)
        try:
            with psycopg.connect(**POSTGRES_PARAMETERS) as connection:
                with connection.transaction():
                    connection.execute(
                        """
                        INSERT INTO p0_protocol.gate_checks (
                            probe_id, check_id, tool_name, operation_id,
                            supplied_revision, current_revision, allowed, reason
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            self.probe_id,
                            str(uuid.uuid4()),
                            tool_name,
                            operation_id,
                            supplied_revision,
                            self.gate.revision,
                            allowed,
                            reason,
                        ),
                    )
                    if not allowed:
                        denied_reason = reason
                    else:
                        denied_reason = None
                        yield connection
            if denied_reason is not None:
                raise GateDenied(f"{tool_name} denied by current Gateway policy: {denied_reason}")
        except psycopg.Error as exc:
            raise GatewayProbeError(
                "isolated Gateway transaction failed; database details are suppressed"
            ) from None

    def query_counter(self, *, policy_revision: str) -> dict[str, int]:
        with self._authorized_transaction("query_counter", None, policy_revision) as connection:
            row = connection.execute(
                """
                SELECT
                    COALESCE((SELECT value FROM p0_protocol.counters WHERE probe_id = %s), 0),
                    (SELECT count(*) FROM p0_protocol.operations WHERE probe_id = %s),
                    (SELECT count(*) FROM p0_protocol.effects WHERE probe_id = %s)
                """,
                (self.probe_id, self.probe_id, self.probe_id),
            ).fetchone()
        return {"counter": row[0], "operations": row[1], "effects": row[2]}

    def submit_operation(
        self,
        *,
        idempotency_key: str,
        tool_call_id: str,
        args: Mapping[str, Any],
        policy_revision: str,
    ) -> tuple[dict[str, Any], bool]:
        """Persist and return an accepted receipt; duplicate dispatch never starts a new row."""
        operation_id = operation_identity(self.probe_id, idempotency_key)
        digest = request_digest("submit_operation", args)
        with self._authorized_transaction(
            "submit_operation", operation_id, policy_revision
        ) as connection:
            existing = connection.execute(
                """
                SELECT request_digest, receipt
                FROM p0_protocol.operations
                WHERE probe_id = %s AND operation_id = %s
                FOR UPDATE
                """,
                (self.probe_id, operation_id),
            ).fetchone()
            if existing is not None:
                if existing[0].strip() != digest:
                    raise IdempotencyConflict(
                        "stable operation identity was reused with a different request digest"
                    )
                return existing[1], False

            count = connection.execute(
                "SELECT count(*) FROM p0_protocol.operations WHERE probe_id = %s",
                (self.probe_id,),
            ).fetchone()[0]
            if count >= MAX_OPERATIONS_PER_PROBE:
                raise ProbeCapacityExceeded("fixed probe operation allowance exceeded")
            receipt = {
                "status": "accepted",
                "operation_id": operation_id,
                "request_digest": digest,
                "accepted_tool_call_id": tool_call_id,
            }
            connection.execute(
                """
                INSERT INTO p0_protocol.operations (
                    probe_id, operation_id, idempotency_key, request_digest,
                    tool_name, status, receipt
                ) VALUES (%s, %s, %s, %s, 'submit_operation', 'accepted', %s)
                """,
                (
                    self.probe_id,
                    operation_id,
                    idempotency_key,
                    digest,
                    Jsonb(receipt),
                ),
            )
        return receipt, True

    def complete_operation(
        self,
        *,
        operation_id: str,
        expected_digest: str,
        result_id: str,
        result: Mapping[str, Any],
        policy_revision: str,
    ) -> tuple[dict[str, Any], bool]:
        """Apply one bounded counter effect and record its final result through Gateway."""
        with self._authorized_transaction(
            "complete_operation", operation_id, policy_revision
        ) as connection:
            normalized_result = dict(result)
            result_digest = hashlib.sha256(
                canonical_json(normalized_result).encode("utf-8")
            ).hexdigest()
            row = connection.execute(
                """
                SELECT request_digest, status, result_id, result_digest, final_result
                FROM p0_protocol.operations
                WHERE probe_id = %s AND operation_id = %s
                FOR UPDATE
                """,
                (self.probe_id, operation_id),
            ).fetchone()
            if row is None:
                raise GatewayProbeError("result refers to an unknown operation")
            if row[0].strip() != expected_digest:
                raise IdempotencyConflict("result request digest does not match the operation")
            if row[1] == "completed":
                if row[2] == result_id and row[3].strip() == result_digest:
                    return row[4], False
                raise ResultConflict("operation already has a different final result")

            effect = connection.execute(
                """
                INSERT INTO p0_protocol.effects (probe_id, operation_id, effect_number, effect_value)
                SELECT %s, %s,
                       COALESCE((SELECT value FROM p0_protocol.counters WHERE probe_id = %s), 0) + 1,
                       1
                ON CONFLICT (probe_id, operation_id) DO NOTHING
                RETURNING effect_number
                """,
                (self.probe_id, operation_id, self.probe_id),
            ).fetchone()
            if effect is None:
                raise GatewayProbeError("effect row exists without a completed operation")
            counter = connection.execute(
                """
                INSERT INTO p0_protocol.counters (probe_id, value)
                VALUES (%s, 1)
                ON CONFLICT (probe_id) DO UPDATE
                    SET value = p0_protocol.counters.value + 1
                RETURNING value
                """,
                (self.probe_id,),
            ).fetchone()[0]
            final_result = {
                **normalized_result,
                "status": "completed",
                "operation_id": operation_id,
                "result_id": result_id,
                "effect_number": effect[0],
                "counter": counter,
            }
            connection.execute(
                """
                UPDATE p0_protocol.operations
                SET status = 'completed', result_id = %s, result_digest = %s, final_result = %s
                WHERE probe_id = %s AND operation_id = %s
                """,
                (
                    result_id,
                    result_digest,
                    Jsonb(final_result),
                    self.probe_id,
                    operation_id,
                ),
            )
        return final_result, True

    def await_operation(
        self,
        *,
        operation_id: str,
        expected_digest: str,
        policy_revision: str,
    ) -> dict[str, Any] | None:
        """Return a final result when ready; None means caller ends this Run and waits."""
        with self._authorized_transaction(
            "await_operation", operation_id, policy_revision
        ) as connection:
            row = connection.execute(
                """
                SELECT request_digest, status, final_result
                FROM p0_protocol.operations
                WHERE probe_id = %s AND operation_id = %s
                """,
                (self.probe_id, operation_id),
            ).fetchone()
            if row is None:
                raise GatewayProbeError("wait refers to an unknown operation")
            if row[0].strip() != expected_digest:
                raise IdempotencyConflict("wait request digest does not match the operation")
            if row[1] != "completed":
                return None
            return row[2]

    def evidence_snapshot(self, *, policy_revision: str) -> dict[str, int]:
        """Query operation/effect counts through the same current Gateway boundary."""
        snapshot = self.query_counter(policy_revision=policy_revision)
        with self._authorized_transaction(
            "query_counter", None, policy_revision
        ) as connection:
            denied = connection.execute(
                """
                SELECT count(*) FILTER (WHERE NOT allowed), count(*)
                FROM p0_protocol.gate_checks
                WHERE probe_id = %s
                """,
                (self.probe_id,),
            ).fetchone()[0]
            gate_checks = connection.execute(
                "SELECT count(*) FROM p0_protocol.gate_checks WHERE probe_id = %s",
                (self.probe_id,),
            ).fetchone()[0]
        return {**snapshot, "denied_gate_checks": denied, "gate_checks": gate_checks}


def main() -> None:
    gateway = Gateway()
    server_version = Gateway.prepare()
    gateway.reset_scope()
    snapshot = gateway.evidence_snapshot(policy_revision=gateway.gate.revision)
    print(
        json.dumps(
            {
                "probe": "SDK-03/04 isolated Gateway",
                "postgresql": server_version,
                "schema": SCHEMA,
                "probe_id": gateway.probe_id,
                "initial_snapshot": snapshot,
                "side_effect_scope": "bounded counter; no application data",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
