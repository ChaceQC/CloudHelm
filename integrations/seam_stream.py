"""Bounded usage capture outside DBOS; no prompts, credentials or deltas persist."""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from integrations.seam_admission import ExecutionScope, SeamAdmission
from scripts.p0.model_boundary import AdmissionDenied, RequestBudget

INPUT_BOUND = 65536
STREAM_LIVE_REVISION = "r2"
STREAM_REQUEST_CAP = 4
STREAM_DISCONNECT_POINT = "after_http_200_before_consuming_incomplete_chunk"


class InjectedDisconnectReadError(httpx.ReadError):
    """The deliberate A02d cut after an HTTP 200 and before parsing its stream."""


def exception_evidence(error: BaseException) -> dict[str, Any]:
    """Expose exception types only, including wrapped SDK causes, without messages."""
    pending = [error]
    seen: set[int] = set()
    chain: list[BaseException] = []
    while pending and len(chain) < 16:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        chain.append(current)
        for attribute in ("__cause__", "__context__", "cause"):
            try:
                linked = getattr(current, attribute, None)
            except Exception:
                continue
            if isinstance(linked, BaseException):
                pending.append(linked)
    return {
        "error_chain": [type(item).__name__ for item in chain],
        "read_error_chain": [
            type(item).__name__ for item in chain if isinstance(item, httpx.ReadError)
        ],
        "read_error_seen": any(isinstance(item, httpx.ReadError) for item in chain),
        "injected_disconnect_seen": any(
            isinstance(item, InjectedDisconnectReadError) for item in chain
        ),
    }


def stream_assertion_errors(report: Mapping[str, Any]) -> list[str]:
    """Return stable failure labels for the fixed A02d stream evidence shape."""
    errors: list[str] = []
    if (
        report.get("candidate") != f"SDK-A01-C1-{STREAM_LIVE_REVISION}"
        or report.get("revision") != STREAM_LIVE_REVISION
        or report.get("batch_key") != f"p0-sdk-a01-c1-live-{STREAM_LIVE_REVISION}"
    ):
        errors.append("fixed_revision_identity")
    if type(report.get("request_limit")) is not int or report.get("request_limit") != STREAM_REQUEST_CAP:
        errors.append("request_limit")
    if type(report.get("real_http")) is not int or report.get("real_http") != STREAM_REQUEST_CAP:
        errors.append("total_request_count")
    scenarios = report.get("scenarios")
    if not isinstance(scenarios, Mapping) or set(scenarios) != {"normal", "disconnect"}:
        return errors + ["scenario_set"]
    for name in ("normal", "disconnect"):
        errors.extend(_scenario_assertion_errors(name, scenarios[name]))
    return errors


def _scenario_assertion_errors(name: str, evidence: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(evidence, Mapping):
        return [f"{name}:scenario_shape"]
    requests = evidence.get("requests")
    if (
        type(evidence.get("requests_sent")) is not int
        or evidence.get("requests_sent") != 2
        or type(evidence.get("real_http")) is not int
        or evidence.get("real_http") != 2
        or not isinstance(requests, list)
        or len(requests) != 2
    ):
        errors.append(f"{name}:request_count")
        requests = requests if isinstance(requests, list) else []
    if any(not isinstance(item, Mapping) or item.get("http_status") != 200 for item in requests):
        errors.append(f"{name}:http_status")
    if (
        type(evidence.get("same_workflow_replay_real_http")) is not int
        or evidence.get("same_workflow_replay_real_http") != 0
        or type(evidence.get("workflow_replay_request_count_before")) is not int
        or type(evidence.get("workflow_replay_request_count_after")) is not int
        or evidence.get("workflow_replay_request_count_before")
        != evidence.get("workflow_replay_request_count_after")
        or evidence.get("same_workflow_replay_equal") is not True
    ):
        errors.append(f"{name}:workflow_replay")
    facts = evidence.get("facts")
    if (
        not isinstance(facts, Mapping)
        or any(
            type(facts.get(key)) is not int or facts.get(key) != 1
            for key in ("operations", "effects", "counter")
        )
        or evidence.get("result_reconciled") is not True
        or evidence.get("duplicate_created") is not False
        or not isinstance(evidence.get("operation_ref"), str)
        or not evidence.get("operation_ref")
    ):
        errors.append(f"{name}:operation_uniqueness")
    persisted = evidence.get("persisted_requests")
    if not isinstance(persisted, list) or len(persisted) != 2 or len(requests) != 2:
        errors.append(f"{name}:persisted_request_count")
    else:
        for observed, stored in zip(requests, persisted, strict=True):
            if not isinstance(observed, Mapping) or not isinstance(stored, Mapping):
                errors.append(f"{name}:persisted_request_shape")
                break
            result = observed.get("result")
            if (
                stored.get("request_id") != observed.get("request_id")
                or not isinstance(result, Mapping)
                or any(stored.get(key) != result.get(key) for key in (
                    "status", "http_status", "usage", "reservation_usd"
                ))
            ):
                errors.append(f"{name}:persisted_request_mismatch")
                break

    injections = evidence.get("injections")
    if name == "normal":
        if (
            evidence.get("outcome") != "completed"
            or evidence.get("error_chain") != []
            or evidence.get("read_error_chain") != []
            or evidence.get("read_error_seen") is not False
            or evidence.get("injected_disconnect_seen") is not False
            or injections != []
            or any(not _complete_success(item) for item in requests)
        ):
            errors.append("normal:completion")
        return errors
    if (
        evidence.get("outcome") != "unknown"
        or evidence.get("read_error_seen") is not True
        or evidence.get("injected_disconnect_seen") is not True
        or not isinstance(evidence.get("error_chain"), list)
        or "InjectedDisconnectReadError" not in evidence.get("error_chain", [])
        or not isinstance(evidence.get("read_error_chain"), list)
        or "InjectedDisconnectReadError" not in evidence.get("read_error_chain", [])
    ):
        errors.append("disconnect:injected_read_error")
    if (
        not isinstance(injections, list)
        or len(injections) != 1
        or not isinstance(requests, list)
        or len(requests) != 2
        or not isinstance(injections[0], Mapping)
        or not isinstance(requests[0], Mapping)
        or not isinstance(requests[1], Mapping)
        or injections[0].get("request_id") != requests[1].get("request_id")
        or injections[0].get("http_status") != 200
        or injections[0].get("point") != STREAM_DISCONNECT_POINT
        or requests[0].get("injected_disconnect") is not False
        or requests[1].get("injected_disconnect") is not True
    ):
        errors.append("disconnect:injection_point")
    if len(requests) == 2:
        first, second = requests
        if not _complete_success(first):
            errors.append("disconnect:first_request_completion")
        result = second.get("result") if isinstance(second, Mapping) else None
        if (
            not isinstance(second, Mapping)
            or second.get("stream_finished") is not False
            or type(second.get("response_completed")) is not int
            or second.get("response_completed") != 0
            or second.get("usage") is not None
            or not isinstance(result, Mapping)
            or result.get("status") != "unknown"
            or result.get("http_status") != 200
            or result.get("usage") is not None
            or result.get("actual_cost_usd") is not None
            or not _positive_reservation(result.get("reservation_usd"))
        ):
            errors.append("disconnect:unknown_reservation")
    return errors


def _complete_success(request: Any) -> bool:
    if not isinstance(request, Mapping):
        return False
    result = request.get("result")
    usage = request.get("usage")
    return (
        request.get("http_status") == 200
        and request.get("stream_finished") is True
        and type(request.get("response_completed")) is int
        and request.get("response_completed") == 1
        and isinstance(usage, Mapping)
        and all(type(usage.get(key)) is int for key in (
            "input_tokens", "output_tokens", "total_tokens"
        ))
        and isinstance(result, Mapping)
        and result.get("status") == "settled"
        and result.get("http_status") == 200
        and isinstance(result.get("usage"), Mapping)
    )


def _positive_reservation(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return Decimal(value) > 0
    except InvalidOperation:
        return False


def usage_fields(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    keys = ("input_tokens", "output_tokens", "total_tokens")
    result = {key: value[key] for key in keys if type(value.get(key)) is int}
    details = value.get("input_tokens_details")
    if isinstance(details, dict):
        result["input_tokens_details"] = {
            key: details[key]
            for key in ("cached_tokens", "cache_write_tokens")
            if type(details.get(key)) is int
        }
    for key in ("cached_input_tokens", "cache_write_tokens"):
        if type(value.get(key)) is int:
            result[key] = value[key]
    return result or None


class MoneyGuardTransport(httpx.AsyncBaseTransport):
    """Called after the durable local request cap, immediately before network I/O."""

    def __init__(self, budget: RequestBudget, admission: SeamAdmission,
                 scope: ExecutionScope, *, disconnect_request: int | None = None):
        self.inner = httpx.AsyncHTTPTransport(retries=0)
        self.budget = budget
        self.admission = admission
        self.scope = scope
        self.disconnect_request = disconnect_request
        self.sent = 0
        self.evidence: list[dict[str, Any]] = []
        self.injected_disconnects: list[dict[str, Any]] = []

    def mark_disconnect_injected(self, request_id: str, status: int) -> None:
        self.injected_disconnects.append({
            "request_id": request_id,
            "http_status": status,
            "point": STREAM_DISCONNECT_POINT,
        })

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        record = self.budget.records[-1]
        payload = json.loads(await request.aread())
        if payload.get("service_tier", "default") != "default":
            raise AdmissionDenied("only_fixed_standard_service_tier_supported")
        if len(request.content) > INPUT_BOUND - 8192:
            raise AdmissionDenied("bounded_context_exceeded")
        reservation = self.admission.reserve_request(
            self.scope, record.request_record_id, record.request_digest,
            INPUT_BOUND, record.max_output_tokens,
        )
        if not reservation["should_send"]:
            raise AdmissionDenied("existing_request_requires_result_reconciliation")
        committed = self.admission.query_request(record.request_record_id)
        if not committed:
            raise AdmissionDenied("business_reservation_not_visible")
        self.sent += 1
        request.headers["accept-encoding"] = "identity"
        try:
            response = await self.inner.handle_async_request(request)
        except Exception:
            self.admission.record_result(record.request_record_id, None)
            raise
        return httpx.Response(
            response.status_code, headers=response.headers,
            stream=BoundedUsageStream(response.stream, self, record.request_record_id,
                                     response.status_code,
                                     self.sent == self.disconnect_request),
            request=request, extensions=response.extensions,
        )

    async def aclose(self) -> None:
        await self.inner.aclose()


class BoundedUsageStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, owner: MoneyGuardTransport,
                 request_id: str, status: int, disconnect: bool):
        self.stream = stream
        self.owner = owner
        self.request_id = request_id
        self.status = status
        self.disconnect = disconnect
        self.buffer = b""
        self.usage: dict[str, Any] | None = None
        self.tier = "default"
        self.finished = False
        self.closed = False
        self.completed_events = 0
        self.function_items = 0

    def consume(self, data: bytes) -> None:
        self.buffer += data
        if len(self.buffer) > 65536:
            raise httpx.ReadError("bounded_stream_event_exceeded")
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if not line.startswith(b"data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except (ValueError, UnicodeError):
                continue
            if event.get("type") == "response.output_item.done":
                self.function_items += event.get("item", {}).get("type") == "function_call"
            if event.get("type") == "response.completed":
                response = event.get("response", {})
                self.usage = usage_fields(response.get("usage"))
                self.tier = response.get("service_tier", "default")
                self.completed_events += 1

    async def __aiter__(self) -> Any:
        async for chunk in self.stream:
            if (
                self.disconnect and self.status == 200 and chunk
                and b"response.completed" not in chunk
            ):
                self.owner.mark_disconnect_injected(self.request_id, self.status)
                raise InjectedDisconnectReadError("p0_a02d_injected_disconnect")
            self.consume(chunk)
            yield chunk
        self.finished = True

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self.stream.aclose()
        result = self.owner.admission.record_result(
            self.request_id, self.usage, service_tier=self.tier, http_status=self.status
        )
        self.owner.evidence.append({
            "request_id": self.request_id, "http_status": self.status,
            "stream_finished": self.finished, "response_completed": self.completed_events,
            "function_items": self.function_items, "usage": self.usage,
            "result": result,
            "injected_disconnect": any(
                item["request_id"] == self.request_id
                for item in self.owner.injected_disconnects
            ),
        })
