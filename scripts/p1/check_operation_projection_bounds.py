"""Focused checks for the shared Task operation projection bound."""

import argparse
import json
from datetime import UTC, datetime
from unittest.mock import patch

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.operation_projection import merge_operation_facts
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.task_control_contracts import OperationClosureFact


class OperationProjectionCheckFailure(RuntimeError):
    """Fixed local check failure code without database or request details."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise OperationProjectionCheckFailure(code)


def _fact(operation_id: str, *, owner_id: str = "p1-operation-check-owner") -> OperationClosureFact:
    return OperationClosureFact(
        operation_ref=EngineeringRef(kind="operation", object_id=operation_id, revision="check-r1"),
        owner_kind="task", owner_id=owner_id,
    )


def _facts(prefix: str, start: int, count: int, *, owner_id: str = "p1-operation-check-owner"):
    return tuple(_fact(f"{prefix}-{index:03d}", owner_id=owner_id) for index in range(start, start + count))


def _expect_boundary(call, code: str) -> None:
    try:
        call()
    except TaskBoundaryError as error:
        _require(error.code == code, "operation_projection_wrong_boundary_error")
    else:
        raise OperationProjectionCheckFailure("operation_projection_boundary_error_missing")


def run_projection_checks() -> dict[str, bool]:
    from modules.collaboration.facts import _read_task_operation_projection

    first = _facts("p1-operation-exact", 0, 64)
    second = _facts("p1-operation-exact", 64, 64)
    exact = merge_operation_facts(first, second)
    _require(len(exact) == 128 and exact == first + second, "operation_projection_128_not_complete")

    _expect_boundary(
        lambda: merge_operation_facts(_facts("p1-operation-over", 0, 128), _facts("p1-operation-over", 128, 1)),
        "task_fact_projection_scope_too_large",
    )
    _expect_boundary(
        lambda: merge_operation_facts((_fact("p1-operation-duplicate"),), (_fact("p1-operation-duplicate"),)),
        "task_fact_projection_duplicate_operation",
    )
    with patch(
        "modules.collaboration.facts.read_operation_facts",
        side_effect=TaskBoundaryError("operation_projection_scope_too_large"),
    ):
        _expect_boundary(
            lambda: _read_task_operation_projection(None, {"task_id": "p1-task-check"}, None),
            "task_fact_projection_scope_too_large",
        )
    for source_error in (
        "engineering_operation_scope_too_large",
        "workspace_operation_scope_too_large",
        "build_operation_scope_too_large",
    ):
        with (
            patch("modules.collaboration.facts.read_operation_facts", return_value=()),
            patch("modules.collaboration.engineering_operations.read_engineering_operation_blockers",
                  side_effect=TaskBoundaryError(source_error)),
        ):
            _expect_boundary(
                lambda: _read_task_operation_projection(None, {"task_id": "p1-task-check"}, None),
                "task_fact_projection_scope_too_large",
            )
    return {
        "exact_128_preserved": True,
        "129_across_sources_rejected_as_scope": True,
        "duplicate_across_sources_classified_separately": True,
        "single_source_scope_error_normalized": True,
        "engineering_source_scope_errors_normalized": True,
    }


def run_application_checks(probe) -> dict[str, bool]:
    """Exercise real TaskApplication result mapping with injected bounded source facts.

    `probe` is the existing scripts.p1.task_probe.TaskProbe backed by a disposable
    initialized DatabaseFixture. This entry point intentionally does not start a
    worker or read credentials from configuration.
    """
    from scripts.p1.task_completion_fixture import stage_completion

    cases = (
        ("128", _facts("p1-operation-exact", 0, 64), _facts("p1-operation-exact", 64, 64), "writes_unsettled"),
        ("129", _facts("p1-operation-over", 0, 128), _facts("p1-operation-over", 128, 1),
         "task_fact_projection_scope_too_large"),
        ("duplicate", (_fact("p1-operation-duplicate"),), (_fact("p1-operation-duplicate"),),
         "task_fact_projection_duplicate_operation"),
    )
    for label, task_facts, engineering, expected in cases:
        seeded = stage_completion(probe)
        with (
            patch("modules.collaboration.facts.read_operation_facts", return_value=task_facts),
            patch("modules.collaboration.engineering_operations.read_engineering_operation_blockers",
                  return_value=engineering),
        ):
            completion = probe.app.complete(
                probe.actor(), seeded.task_id, probe.complete_request(seeded.task_id),
                idempotency_key=probe.key("operation-projection-complete-" + label),
            )
        _require(completion.status_code == 409 and completion.body.code == expected
                 and probe.row(seeded.task_id)["completion_report_id"] is None,
                 "completion_projection_error_not_classified")

        created = probe.create("operation-projection-cancellation-" + label)
        accepted = probe.app.cancel(
            probe.actor(), created.task_id, probe.cancel_request(created.task_id),
            idempotency_key=probe.key("operation-projection-cancel-" + label),
        )
        _require(accepted.status_code == 202, "cancellation_projection_not_accepted")
        with (
            patch("modules.collaboration.facts.read_operation_facts", return_value=task_facts),
            patch("modules.collaboration.engineering_operations.read_engineering_operation_blockers",
                  return_value=engineering),
        ):
            cancellation = probe.app.run_control(accepted.body.command_id)
        cancel_code = "cancellation_physical_execution_unsettled" if label == "128" else expected
        row = probe.row(created.task_id)
        _require(cancellation.outcome in {"blocked", "rejected"} and cancellation.code == cancel_code
                 and row["state"] == "draft" and row["ordinary_progress_closed"],
                 "cancellation_projection_not_left_pending")
    return {
        "completion_128_129_duplicate_map_to_classified_409": True,
        "cancellation_128_129_duplicate_stay_pending_without_exception": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--input-set")
    parser.add_argument("--port", type=int, default=55440)
    args = parser.parse_args()
    report = {"method_revision": "p1-task-operation-projection-r1",
              "started_at_utc": datetime.now(UTC).isoformat(), "human_acceptance": None,
              "scope": "protocol_validation_input_with_injected_projection_sources"}
    try:
        from scripts.p1.engineering_fixture import fixed_inputs

        report["input_before"] = fixed_inputs(args.input_set)
        report["projection"] = run_projection_checks()
        if args.database:
            from scripts.p1.database_fixture import database_fixture
            from scripts.p1.task_probe import TaskProbe

            with database_fixture(port=args.port) as fixture:
                probe = TaskProbe(fixture)
                try:
                    probe.open()
                    report["application"] = run_application_checks(probe)
                finally:
                    probe.close()
            report["database_cleanup"] = "complete"
        report["input_after"] = fixed_inputs(args.input_set)
        _require(report["input_before"] == report["input_after"], "operation_projection_inputs_changed")
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", failure_type=type(error).__name__)
        if isinstance(error, (OperationProjectionCheckFailure, TaskBoundaryError)):
            report["failure_code"] = str(error)
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
