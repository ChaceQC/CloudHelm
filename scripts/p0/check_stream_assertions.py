"""Check A02d stream assertions with synthetic, non-supplier evidence."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from integrations.seam_stream import (
    InjectedDisconnectReadError,
    STREAM_DISCONNECT_POINT,
    STREAM_LIVE_REVISION,
    STREAM_REQUEST_CAP,
    exception_evidence,
    stream_assertion_errors,
)


def _usage(input_tokens: int) -> dict[str, int]:
    return {
        "input_tokens": input_tokens,
        "output_tokens": 8,
        "total_tokens": input_tokens + 8,
    }


def _request(request_id: str, *, complete: bool, injected: bool = False) -> dict[str, Any]:
    usage = _usage(12) if complete else None
    result = {
        "request_id": request_id,
        "status": "settled" if complete else "unknown",
        "http_status": 200,
        "usage": usage,
        "actual_cost_usd": "0.000012" if complete else None,
        "reservation_usd": "0.016768",
    }
    return {
        "request_id": request_id,
        "http_status": 200,
        "stream_finished": complete,
        "response_completed": 1 if complete else 0,
        "usage": usage,
        "result": result,
        "injected_disconnect": injected,
    }


def _scenario(name: str) -> dict[str, Any]:
    first = _request(f"synthetic-{name}-1", complete=True)
    second = _request(
        f"synthetic-{name}-2", complete=name == "normal", injected=name == "disconnect"
    )
    requests = [first, second]
    if name == "disconnect":
        second["result"].update({"status": "unknown", "usage": None, "actual_cost_usd": None})
    injections = (
        [{
            "request_id": second["request_id"],
            "http_status": 200,
            "point": STREAM_DISCONNECT_POINT,
        }]
        if name == "disconnect"
        else []
    )
    stored = [
        {
            "request_id": item["request_id"],
            "status": item["result"]["status"],
            "http_status": item["result"]["http_status"],
            "usage": item["result"]["usage"],
            "reservation_usd": item["result"]["reservation_usd"],
        }
        for item in requests
    ]
    return {
        "outcome": "unknown" if name == "disconnect" else "completed",
        "error_type": "InjectedDisconnectReadError" if name == "disconnect" else None,
        "error_chain": ["InjectedDisconnectReadError"] if name == "disconnect" else [],
        "read_error_chain": ["InjectedDisconnectReadError"] if name == "disconnect" else [],
        "read_error_seen": name == "disconnect",
        "injected_disconnect_seen": name == "disconnect",
        "requests_sent": 2,
        "real_http": 2,
        "requests": requests,
        "injections": injections,
        "persisted_requests": stored,
        "workflow_replay_request_count_before": 2 if name == "normal" else 4,
        "workflow_replay_request_count_after": 2 if name == "normal" else 4,
        "same_workflow_replay_real_http": 0,
        "same_workflow_replay_equal": True,
        "operation_ref": f"synthetic-operation-{name}",
        "facts": {"counter": 1, "operations": 1, "effects": 1},
        "duplicate_created": False,
        "result_reconciled": True,
    }


def _valid_report() -> dict[str, Any]:
    return {
        "candidate": f"SDK-A01-C1-{STREAM_LIVE_REVISION}",
        "revision": STREAM_LIVE_REVISION,
        "batch_key": f"p0-sdk-a01-c1-live-{STREAM_LIVE_REVISION}",
        "request_limit": STREAM_REQUEST_CAP,
        "real_http": STREAM_REQUEST_CAP,
        "scenarios": {name: _scenario(name) for name in ("normal", "disconnect")},
    }


def _expect_rejected(name: str, mutate: Any) -> None:
    report = deepcopy(_valid_report())
    mutate(report)
    if not stream_assertion_errors(report):
        raise AssertionError(f"synthetic rejection case accepted: {name}")


def _check_exception_chain() -> None:
    try:
        try:
            raise InjectedDisconnectReadError("synthetic-safe")
        except InjectedDisconnectReadError as cause:
            raise RuntimeError("synthetic-safe-wrapper") from cause
    except RuntimeError as wrapped:
        facts = exception_evidence(wrapped)
    if (
        facts["read_error_seen"] is not True
        or facts["injected_disconnect_seen"] is not True
        or "InjectedDisconnectReadError" not in facts["read_error_chain"]
    ):
        raise AssertionError("wrapped injected ReadError was not preserved in safe evidence")
    unrelated = exception_evidence(httpx.ReadError("synthetic-safe-other-read-error"))
    if unrelated["read_error_seen"] is not True or unrelated["injected_disconnect_seen"] is not False:
        raise AssertionError("unrelated ReadError was confused with the injected disconnect")


def main() -> int:
    _check_exception_chain()
    report = _valid_report()
    if stream_assertion_errors(report):
        raise AssertionError("valid synthetic normal and disconnect evidence was rejected")

    def ordinary_exception(report: dict[str, Any]) -> None:
        scenario = report["scenarios"]["disconnect"]
        scenario.update({
            "error_type": "RuntimeError", "error_chain": ["RuntimeError"],
            "read_error_chain": [],
            "read_error_seen": False, "injected_disconnect_seen": False,
            "injections": [],
        })
        scenario["requests"][1]["injected_disconnect"] = False

    def before_http_response(report: dict[str, Any]) -> None:
        scenario = report["scenarios"]["disconnect"]
        scenario["requests"][1]["http_status"] = None
        scenario["requests"][1]["result"]["http_status"] = None
        scenario.update({
            "error_chain": ["ConnectError"], "read_error_seen": False,
            "read_error_chain": [],
            "injected_disconnect_seen": False, "injections": [],
        })
        scenario["requests"][1]["injected_disconnect"] = False
        scenario["persisted_requests"][1]["http_status"] = None

    def unrelated_read_error(report: dict[str, Any]) -> None:
        scenario = report["scenarios"]["disconnect"]
        scenario.update({
            "error_chain": ["ReadError"], "read_error_seen": True,
            "read_error_chain": ["ReadError"],
            "injected_disconnect_seen": False, "injections": [],
        })
        scenario["requests"][1]["injected_disconnect"] = False

    def stream_upper_bound_error(report: dict[str, Any]) -> None:
        scenario = report["scenarios"]["disconnect"]
        scenario.update({
            "error_chain": ["ReadError"], "read_error_chain": ["ReadError"],
            "read_error_seen": True, "injected_disconnect_seen": False,
            "injections": [],
        })
        scenario["requests"][1]["injected_disconnect"] = False

    def wrong_injection_point(report: dict[str, Any]) -> None:
        report["scenarios"]["disconnect"]["injections"][0]["point"] = "stream_upper_bound"

    def complete_disconnect_stream(report: dict[str, Any]) -> None:
        scenario = report["scenarios"]["disconnect"]
        second = scenario["requests"][1]
        second.update({
            "stream_finished": True,
            "response_completed": 1,
            "usage": _usage(12),
            "injected_disconnect": False,
        })
        second["result"].update({
            "status": "settled", "usage": _usage(12), "actual_cost_usd": "0.000012",
        })
        scenario["persisted_requests"][1].update({
            "status": "settled", "usage": _usage(12),
        })

    def wrong_request_count(report: dict[str, Any]) -> None:
        report["scenarios"]["disconnect"]["requests_sent"] = 1

    def non_200_disconnect(report: dict[str, Any]) -> None:
        scenario = report["scenarios"]["disconnect"]
        scenario["requests"][1]["http_status"] = 503
        scenario["requests"][1]["result"]["http_status"] = 503

    def non_200_normal(report: dict[str, Any]) -> None:
        scenario = report["scenarios"]["normal"]
        scenario["requests"][0]["http_status"] = 503
        scenario["requests"][0]["result"]["http_status"] = 503

    def normal_incomplete_stream(report: dict[str, Any]) -> None:
        scenario = report["scenarios"]["normal"]
        request = scenario["requests"][1]
        request.update({"stream_finished": False, "response_completed": 0, "usage": None})
        request["result"].update({"status": "unknown", "usage": None, "actual_cost_usd": None})
        scenario["persisted_requests"][1].update({"status": "unknown", "usage": None})

    def settled_unknown_reservation(report: dict[str, Any]) -> None:
        scenario = report["scenarios"]["disconnect"]
        scenario["requests"][1]["result"]["status"] = "settled"
        scenario["persisted_requests"][1]["status"] = "settled"

    cases = (
        ("ordinary_exception", ordinary_exception),
        ("failure_before_http_200", before_http_response),
        ("unrelated_read_error", unrelated_read_error),
        ("stream_upper_bound_error", stream_upper_bound_error),
        ("wrong_injection_point", wrong_injection_point),
        ("complete_disconnect_stream", complete_disconnect_stream),
        ("wrong_request_count", wrong_request_count),
        ("non_200_disconnect", non_200_disconnect),
        ("non_200_normal", non_200_normal),
        ("normal_incomplete_stream", normal_incomplete_stream),
        ("unknown_reservation_settled", settled_unknown_reservation),
    )
    for name, mutate in cases:
        _expect_rejected(name, mutate)

    print(json.dumps({
        "check": "p0.1-A02d stream assertions",
        "result": "passed",
        "synthetic_cases": 3 + len(cases),
        "supplier_evidence": False,
        "scope": "assertion behavior only",
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
