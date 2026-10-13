from __future__ import annotations

import contextvars
import gzip
import hashlib
import json
import secrets
import sqlite3
import tomllib
import uuid
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx

MODEL_NAME = "gpt-6-luna"
REASONING_EFFORT = "max"
BASE_URL = "https://s2a.chacewebsite.cn/v1"
WIRE_API = "responses"
CONFIG_PATH = Path("/mnt/c/Users/q-lau/.codex/config.toml")
MAX_OUTPUT_TOKENS = 2048
PROBE_OUTPUT_CAP = 512
FIXED_BATCH_REQUEST_CAP = 6
LIVE_CANDIDATE_REVISION = "SDK-02-C2"
PREVIOUS_REAL_HTTP_COUNT = 18
TASK_CUMULATIVE_HTTP_CAP = 19
STREAM_CANDIDATE_REVISION = "SDK-02-C3-STREAM"
STREAM_BATCH_KEY = "p0-sdk02-authorized-live-candidate-3-stream"
STREAM_REQUEST_CAP = 1
STREAM_EVENT_LIMIT = 2048
STREAM_EVENT_TYPE_LIMIT = 32
JOURNAL_PATH = Path(__file__).resolve().parents[2] / ".thesis-work" / "runtime-data" / "p0-sdk02.sqlite3"
LIVE_BATCH_KEY = "p0-sdk02-authorized-live-candidate-2"
FAULT_BATCH_KEY = "p0-sdk02-offline-fault-v1"
FAULT_UNKNOWN_BATCH_KEY = "p0-sdk02-offline-unknown-v1"


class AdmissionDenied(RuntimeError):
    """A local request gate rejected an outbound attempt."""


class SafeConfigurationError(RuntimeError):
    """The explicitly authorized provider configuration is unavailable."""


@dataclass(frozen=True)
class ProviderConfig:
    model: str
    reasoning: str
    base_url: str
    wire_api: str
    provider_name: str
    credential: str = field(repr=False)


def _authorized_config() -> ProviderConfig:
    """Read the one authorized provider, without exposing its credential."""
    try:
        with CONFIG_PATH.open("rb") as config_file:
            values = tomllib.load(config_file)
        provider_name = values["model_provider"]
        provider = values["model_providers"][provider_name]
        config = ProviderConfig(
            # The task authorization fixes this model even if Codex's interactive
            # default model changes independently.
            model=MODEL_NAME,
            reasoning=values["model_reasoning_effort"],
            base_url=provider["base_url"],
            wire_api=provider["wire_api"],
            provider_name=provider_name,
            credential=provider["experimental_bearer_token"],
        )
    except Exception:
        raise SafeConfigurationError("authorized provider configuration unavailable") from None

    if (
        config.model != MODEL_NAME
        or config.reasoning != REASONING_EFFORT
        or config.base_url.rstrip("/") != BASE_URL
        or config.wire_api != WIRE_API
        or not config.credential
    ):
        raise SafeConfigurationError("authorized provider does not match the fixed probe")
    return config


@dataclass
class RequestRecord:
    batch_id: str
    request_record_id: str
    scenario: str
    logical_call: int
    attempt: int
    request_digest: str
    max_output_tokens: int
    reserved_output_tokens: int
    stream_requested: bool = False
    http_status: int | None = None
    transport_error_type: str | None = None
    vendor_usage: dict[str, int | None] | None = None
    usage_source: str | None = None
    provider_response_id: str | None = None
    provider_request_id: str | None = None
    response_content_type: str | None = None
    response_content_encoding: str | None = None
    response_shape: dict[str, Any] | None = None
    journal_outcome: str = "reserved"
    preflight_commit_visible: bool = False


class RequestJournal:
    """Small append-only SQLite journal for preflight reservations and results."""

    def __init__(
        self,
        path: Path,
        probe_key: str,
        max_requests: int,
        max_reserved_output_tokens: int,
    ) -> None:
        self.path = path
        self.probe_key = probe_key
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self.batch_id, self.max_requests, self.max_reserved_output_tokens = self._open_batch(
            max_requests, max_reserved_output_tokens
        )
        self.reserved_requests, self.reserved_output_tokens = self._reserved()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS probe_batches ("
                "probe_key TEXT PRIMARY KEY, batch_id TEXT NOT NULL UNIQUE, "
                "max_requests INTEGER NOT NULL, max_output_tokens INTEGER NOT NULL, "
                "reserved_requests INTEGER NOT NULL DEFAULT 0, "
                "reserved_output_tokens INTEGER NOT NULL DEFAULT 0, created_utc TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS request_records ("
                "request_record_id TEXT PRIMARY KEY, probe_key TEXT NOT NULL, batch_id TEXT NOT NULL, "
                "scenario TEXT NOT NULL, logical_call INTEGER NOT NULL, attempt INTEGER NOT NULL, "
                "request_digest TEXT NOT NULL, max_output_tokens INTEGER NOT NULL, "
                "reserved_output_tokens INTEGER NOT NULL, stream_requested INTEGER NOT NULL DEFAULT 0, "
                "created_utc TEXT NOT NULL, "
                "FOREIGN KEY(probe_key) REFERENCES probe_batches(probe_key))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS request_results ("
                "result_id INTEGER PRIMARY KEY AUTOINCREMENT, request_record_id TEXT NOT NULL, "
                "outcome TEXT NOT NULL, http_status INTEGER, error_type TEXT, vendor_usage_json TEXT, "
                "usage_source TEXT, provider_response_id TEXT, provider_request_id TEXT, "
                "content_type TEXT, content_encoding TEXT, "
                "response_shape_json TEXT, created_utc TEXT NOT NULL, "
                "FOREIGN KEY(request_record_id) REFERENCES request_records(request_record_id))"
            )
            request_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(request_records)")
            }
            if "stream_requested" not in request_columns:
                connection.execute(
                    "ALTER TABLE request_records ADD COLUMN stream_requested INTEGER NOT NULL DEFAULT 0"
                )
            result_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(request_results)")
            }
            if "provider_request_id" not in result_columns:
                connection.execute(
                    "ALTER TABLE request_results ADD COLUMN provider_request_id TEXT"
                )
        finally:
            connection.close()

    def _open_batch(self, max_requests: int, max_output_tokens: int) -> tuple[str, int, int]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM probe_batches WHERE probe_key=?", (self.probe_key,)
            ).fetchone()
            if row is None:
                batch_id = uuid.uuid4().hex
                connection.execute(
                    "INSERT INTO probe_batches "
                    "(probe_key,batch_id,max_requests,max_output_tokens,created_utc) "
                    "VALUES (?,?,?,?,?)",
                    (self.probe_key, batch_id, max_requests, max_output_tokens, _utc_now()),
                )
                connection.commit()
                return batch_id, max_requests, max_output_tokens
            fixed_requests = min(max_requests, row["max_requests"])
            fixed_output_tokens = min(max_output_tokens, row["max_output_tokens"])
            connection.execute(
                "UPDATE probe_batches SET max_requests=?, max_output_tokens=? WHERE probe_key=?",
                (fixed_requests, fixed_output_tokens, self.probe_key),
            )
            connection.commit()
            return row["batch_id"], fixed_requests, fixed_output_tokens
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _reserved(self) -> tuple[int, int]:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT reserved_requests,reserved_output_tokens FROM probe_batches WHERE probe_key=?",
                (self.probe_key,),
            ).fetchone()
            if row is None:
                raise RuntimeError("probe batch journal missing")
            return row["reserved_requests"], row["reserved_output_tokens"]
        finally:
            connection.close()

    def reserve_request(self, record: RequestRecord) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM probe_batches WHERE probe_key=?", (self.probe_key,)
            ).fetchone()
            if row is None or row["batch_id"] != record.batch_id:
                raise AdmissionDenied("stable batch identity changed")
            existing = connection.execute(
                "SELECT request_digest FROM request_records WHERE request_record_id=?",
                (record.request_record_id,),
            ).fetchone()
            if existing is not None:
                reason = (
                    "request identity reused with different digest"
                    if existing["request_digest"] != record.request_digest
                    else "request identity already journaled; replay blocked"
                )
                raise AdmissionDenied(reason)
            if row["reserved_requests"] >= row["max_requests"]:
                raise AdmissionDenied("request-count budget exhausted")
            if row["reserved_output_tokens"] + record.reserved_output_tokens > row["max_output_tokens"]:
                raise AdmissionDenied("output-token budget exhausted")
            connection.execute(
                "INSERT INTO request_records "
                "(request_record_id,probe_key,batch_id,scenario,logical_call,attempt,request_digest,"
                "max_output_tokens,reserved_output_tokens,stream_requested,created_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record.request_record_id,
                    self.probe_key,
                    self.batch_id,
                    record.scenario,
                    record.logical_call,
                    record.attempt,
                    record.request_digest,
                    record.max_output_tokens,
                    record.reserved_output_tokens,
                    int(record.stream_requested),
                    _utc_now(),
                ),
            )
            connection.execute(
                "UPDATE probe_batches SET reserved_requests=reserved_requests+1, "
                "reserved_output_tokens=reserved_output_tokens+? WHERE probe_key=?",
                (record.reserved_output_tokens, self.probe_key),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def assert_reservation_visible(self, record: RequestRecord) -> bool:
        """Confirm the committed reservation from a fresh SQLite connection."""
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT r.batch_id,r.request_digest,r.reserved_output_tokens,r.stream_requested,"
                "b.reserved_requests,b.reserved_output_tokens AS batch_output_tokens "
                "FROM request_records r JOIN probe_batches b USING(probe_key) "
                "WHERE r.request_record_id=?",
                (record.request_record_id,),
            ).fetchone()
            return bool(
                row
                and row["batch_id"] == record.batch_id
                and row["request_digest"] == record.request_digest
                and row["reserved_output_tokens"] == record.reserved_output_tokens
                and bool(row["stream_requested"]) == record.stream_requested
                and row["reserved_requests"] > 0
                and row["batch_output_tokens"] >= record.reserved_output_tokens
            )
        finally:
            connection.close()

    def append_result(self, record: RequestRecord, outcome: str) -> None:
        connection = self._connect()
        try:
            connection.execute(
                "INSERT INTO request_results "
                "(request_record_id,outcome,http_status,error_type,vendor_usage_json,usage_source,"
                "provider_response_id,provider_request_id,content_type,content_encoding,"
                "response_shape_json,created_utc) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record.request_record_id,
                    outcome,
                    record.http_status,
                    record.transport_error_type,
                    _safe_json(record.vendor_usage),
                    record.usage_source,
                    record.provider_response_id,
                    record.provider_request_id,
                    record.response_content_type,
                    record.response_content_encoding,
                    _safe_json(record.response_shape),
                    _utc_now(),
                ),
            )
            connection.commit()
            record.journal_outcome = outcome
        finally:
            connection.close()

    def records(self) -> list[RequestRecord]:
        connection = self._connect()
        try:
            saved = connection.execute(
                "SELECT * FROM request_records WHERE probe_key=? ORDER BY created_utc,request_record_id",
                (self.probe_key,),
            ).fetchall()
            records = []
            for row in saved:
                latest = connection.execute(
                    "SELECT * FROM request_results WHERE request_record_id=? "
                    "ORDER BY result_id DESC LIMIT 1",
                    (row["request_record_id"],),
                ).fetchone()
                result = dict(latest) if latest is not None else {}
                preflight = connection.execute(
                    "SELECT 1 FROM request_results WHERE request_record_id=? "
                    "AND outcome='preflight_commit_visible' LIMIT 1",
                    (row["request_record_id"],),
                ).fetchone()
                records.append(
                    RequestRecord(
                        request_record_id=row["request_record_id"],
                        batch_id=row["batch_id"],
                        scenario=row["scenario"],
                        logical_call=row["logical_call"],
                        attempt=row["attempt"],
                        request_digest=row["request_digest"],
                        max_output_tokens=row["max_output_tokens"],
                        reserved_output_tokens=row["reserved_output_tokens"],
                        stream_requested=bool(row["stream_requested"]),
                        http_status=result.get("http_status"),
                        transport_error_type=result.get("error_type"),
                        vendor_usage=json.loads(result["vendor_usage_json"])
                        if result.get("vendor_usage_json")
                        else None,
                        usage_source=result.get("usage_source"),
                        provider_response_id=result.get("provider_response_id"),
                        provider_request_id=result.get("provider_request_id"),
                        response_content_type=result.get("content_type"),
                        response_content_encoding=result.get("content_encoding"),
                        response_shape=json.loads(result["response_shape_json"])
                        if result.get("response_shape_json")
                        else None,
                        journal_outcome=(
                            "unknown"
                            if result.get("outcome") == "preflight_commit_visible"
                            else result.get("outcome", "unknown")
                        ),
                        preflight_commit_visible=preflight is not None,
                    )
                )
            return records
        finally:
            connection.close()


@dataclass
class RequestBudget:
    journal: RequestJournal = field(repr=False)
    records: list[RequestRecord] = field(default_factory=list)
    max_requests: int = field(init=False)
    max_reserved_output_tokens: int = field(init=False)
    reserved_requests: int = field(init=False)
    reserved_output_tokens: int = field(init=False)
    batch_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.batch_id = self.journal.batch_id
        self.max_requests = self.journal.max_requests
        self.max_reserved_output_tokens = self.journal.max_reserved_output_tokens
        self.reserved_requests = self.journal.reserved_requests
        self.reserved_output_tokens = self.journal.reserved_output_tokens

    def reserve(
        self,
        scenario: str,
        logical_call: int,
        attempt: int,
        body: bytes,
        output_cap: int,
        stream_requested: bool = False,
    ) -> RequestRecord:
        if not 0 < output_cap <= MAX_OUTPUT_TOKENS:
            raise AdmissionDenied("output-token ceiling rejected")
        digest = hashlib.sha256(body).hexdigest()
        identity = f"{self.batch_id}:{scenario}:{logical_call}:{attempt}"
        request_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        record = RequestRecord(
            batch_id=self.batch_id,
            request_record_id=f"mr_{request_id}",
            scenario=scenario,
            logical_call=logical_call,
            attempt=attempt,
            request_digest=digest,
            max_output_tokens=output_cap,
            reserved_output_tokens=output_cap,
            stream_requested=stream_requested,
        )
        self.journal.reserve_request(record)
        self.records.append(record)
        self.reserved_requests += 1
        self.reserved_output_tokens += output_cap
        return record


@dataclass
class RequestScope:
    scenario: str
    logical_call: int = 0
    max_logical_calls: int = 1
    require_stream: bool = False


class AdmissionTransport(httpx.AsyncBaseTransport):
    """Recheck authorization and reserve a record immediately before HTTP I/O."""

    def __init__(
        self,
        inner: httpx.AsyncBaseTransport,
        budget: RequestBudget,
        *,
        live: bool,
        expected_config: ProviderConfig | None = None,
    ) -> None:
        self.inner = inner
        self.budget = budget
        self.live = live
        self.expected_config = expected_config
        self.active_scope: contextvars.ContextVar[RequestScope | None] = contextvars.ContextVar(
            "cloudhelm_model_request_scope", default=None
        )

    @contextmanager
    def scenario(
        self,
        name: str,
        *,
        max_logical_calls: int = 1,
        require_stream: bool = False,
    ) -> Iterator[RequestScope]:
        scope = RequestScope(
            scenario=name,
            max_logical_calls=max_logical_calls,
            require_stream=require_stream,
        )
        token = self.active_scope.set(scope)
        try:
            yield scope
        finally:
            self.active_scope.reset(token)

    def _current_authorization(self) -> None:
        if not self.live or self.expected_config is None:
            return
        current = _authorized_config()
        if (
            current.model != self.expected_config.model
            or current.reasoning != self.expected_config.reasoning
            or current.base_url.rstrip("/") != self.expected_config.base_url.rstrip("/")
            or current.wire_api != self.expected_config.wire_api
            or current.provider_name != self.expected_config.provider_name
            or not secrets.compare_digest(current.credential, self.expected_config.credential)
        ):
            raise AdmissionDenied("current provider authorization changed")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        scope = self.active_scope.get()
        if scope is None:
            raise AdmissionDenied("request has no active authorized scope")
        self._current_authorization()
        if request.url.scheme != "https" or request.url.host != "s2a.chacewebsite.cn":
            raise AdmissionDenied("provider destination rejected")
        if request.url.path.rstrip("/") != "/v1/responses" or request.url.query:
            raise AdmissionDenied("Responses endpoint rejected")

        try:
            body = await request.aread()
            payload = json.loads(body)
            if payload.get("model") != MODEL_NAME:
                raise AdmissionDenied("model outside authorized probe")
            reasoning = payload.get("reasoning") or {}
            if reasoning.get("effort") != REASONING_EFFORT:
                raise AdmissionDenied("reasoning setting outside authorized probe")
            output_cap = payload.get("max_output_tokens")
            if not isinstance(output_cap, int) or isinstance(output_cap, bool):
                raise AdmissionDenied("explicit max_output_tokens required")
            stream_requested = payload.get("stream") is True
            if stream_requested != scope.require_stream:
                raise AdmissionDenied("request streaming mode differs from probe scope")
            retry_header = request.headers.get("x-stainless-retry-count", "0")
            retry_count = int(retry_header)
        except AdmissionDenied:
            raise
        except Exception:
            raise AdmissionDenied("request shape could not be verified") from None

        if retry_count == 0:
            scope.logical_call += 1
        if retry_count > 1 or scope.logical_call > scope.max_logical_calls:
            raise AdmissionDenied("SDK retry or scenario request limit exceeded")
        record = self.budget.reserve(
            scope.scenario,
            scope.logical_call,
            retry_count,
            body,
            output_cap,
            stream_requested=stream_requested,
        )
        if not self.budget.journal.assert_reservation_visible(record):
            raise AdmissionDenied("committed reservation not visible before HTTP")
        record.preflight_commit_visible = True
        self.budget.journal.append_result(record, "preflight_commit_visible")
        forwarded = httpx.Request(
            request.method,
            request.url,
            headers=request.headers,
            content=body,
            extensions=request.extensions,
        )
        try:
            response = await self.inner.handle_async_request(forwarded)
        except Exception as exc:
            record.transport_error_type = type(exc).__name__
            record.journal_outcome = "unknown"
            self.budget.journal.append_result(record, "unknown")
            raise
        record.http_status = response.status_code
        record.response_content_type = response.headers.get("content-type")
        record.response_content_encoding = response.headers.get("content-encoding")
        record.provider_request_id = response.headers.get("x-request-id")
        record.journal_outcome = "http_response_received"
        self.budget.journal.append_result(record, "http_response_received")
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=UsageCaptureStream(
                response.stream,
                record,
                self.budget.journal,
                streaming=record.stream_requested,
            ),
            extensions=response.extensions,
            request=forwarded,
        )

    async def aclose(self) -> None:
        await self.inner.aclose()


class UsageCaptureStream(httpx.AsyncByteStream):
    """Retain only Responses usage fields; never retain or print response text."""

    def __init__(
        self,
        inner: httpx.AsyncByteStream,
        record: RequestRecord,
        journal: RequestJournal,
        *,
        streaming: bool,
    ) -> None:
        self.inner = inner
        self.record = record
        self.journal = journal
        self.streaming = streaming

    async def __aiter__(self) -> Any:
        body = bytearray()
        try:
            async for chunk in self.inner:
                body.extend(chunk)
                yield chunk
        except Exception as exc:
            self.record.transport_error_type = type(exc).__name__
            self.record.journal_outcome = "unknown"
            self.journal.append_result(self.record, "unknown")
            body.clear()
            raise
        self.record.vendor_usage, self.record.response_shape = _extract_vendor_usage(
            bytes(body), self.record.response_content_encoding, streaming=self.streaming
        )
        if self.record.response_shape is not None:
            self.record.response_shape["content_type"] = self.record.response_content_type
        if self.record.vendor_usage is not None:
            self.record.usage_source = "Responses HTTP response"
            self.record.journal_outcome = "vendor_usage_observed"
            self.journal.append_result(self.record, "vendor_usage_observed")
        body.clear()

    async def aclose(self) -> None:
        await self.inner.aclose()


def _extract_vendor_usage(
    body: bytes, content_encoding: str | None, *, streaming: bool = False
) -> tuple[dict[str, int | None] | None, dict[str, Any] | None]:
    try:
        if content_encoding == "gzip" or body.startswith(b"\x1f\x8b"):
            body = gzip.decompress(body)
        elif content_encoding == "deflate":
            body = zlib.decompress(body)
    except Exception:
        return None, {"decode": "failed"}

    documents: list[dict[str, Any]] = []
    try:
        decoded = json.loads(body)
        if isinstance(decoded, dict):
            documents.append(decoded)
    except Exception:
        for line in body.splitlines():
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if not data or data == b"[DONE]":
                continue
            try:
                event = json.loads(data)
                if isinstance(event, dict):
                    documents.append(event)
            except Exception:
                continue

    shape: dict[str, Any] = {
        "content_encoding": content_encoding,
        "event_type_counts": {},
        "event_count_truncated": False,
    }
    event_count = 0
    for document in documents:
        if not streaming:
            shape["document_keys"] = sorted(document.keys())
        event_type = document.get("type")
        if streaming and isinstance(event_type, str):
            if event_count >= STREAM_EVENT_LIMIT:
                shape["event_count_truncated"] = True
            else:
                counts = shape["event_type_counts"]
                count_key = event_type
                if count_key not in counts and len(counts) >= STREAM_EVENT_TYPE_LIMIT:
                    count_key = "__other__"
                counts[count_key] = counts.get(count_key, 0) + 1
                event_count += 1
        usage = document.get("usage")
        if usage is None and isinstance(document.get("response"), dict):
            usage = document["response"].get("usage")
        if usage is None and isinstance(document.get("data"), dict):
            usage = document["data"].get("usage")
        if not isinstance(usage, dict):
            continue
        details = usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}
        return (
            {
                "input_tokens": _optional_int(usage.get("input_tokens", usage.get("prompt_tokens"))),
                "output_tokens": _optional_int(usage.get("output_tokens", usage.get("completion_tokens"))),
                "total_tokens": _optional_int(usage.get("total_tokens")),
                "cached_input_tokens": _optional_int(
                    details.get("cached_tokens", details.get("cache_read_input_tokens"))
                ),
            },
            shape,
        )
    return None, shape if documents else None


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_json(value: Any) -> str | None:
    return json.dumps(value, sort_keys=True, separators=(",", ":")) if value is not None else None


def safe_status(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def safe_record(record: RequestRecord) -> dict[str, Any]:
    return {
        "batch_id": record.batch_id,
        "request_record_id": record.request_record_id,
        "scenario": record.scenario,
        "logical_call": record.logical_call,
        "attempt": record.attempt,
        "request_digest": record.request_digest,
        "max_output_tokens": record.max_output_tokens,
        "reserved_output_tokens": record.reserved_output_tokens,
        "http_status": record.http_status,
        "transport_error_type": record.transport_error_type,
        "vendor_usage": record.vendor_usage,
        "usage_source": record.usage_source,
        "provider_response_id": record.provider_response_id,
        "provider_request_id": record.provider_request_id,
        "response_content_type": record.response_content_type,
        "response_content_encoding": record.response_content_encoding,
        "response_shape": record.response_shape,
        "journal_outcome": record.journal_outcome,
        "preflight_commit_visible": record.preflight_commit_visible,
        "stream_requested": record.stream_requested,
    }
