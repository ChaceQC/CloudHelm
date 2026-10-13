"""Bounded usage capture outside DBOS; no prompts, credentials or deltas persist."""

from __future__ import annotations

import json
from typing import Any

import httpx

from integrations.seam_admission import ExecutionScope, SeamAdmission
from scripts.p0.model_boundary import AdmissionDenied, RequestBudget

INPUT_BOUND = 65536


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
            if self.disconnect and self.status == 200:
                raise httpx.ReadError("injected_disconnect_after_committed_operation")
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
        })
