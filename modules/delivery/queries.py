"""Validated immutable BuildRun reads and conservative Task closure projection."""

import rfc8785
from sqlalchemy import select

from database.commands import get_by_id
from database.uow import require_transaction
from modules.collaboration.records import reference_key
from modules.delivery.errors import BuildBoundaryError
from modules.delivery.tables import build_runs
from modules.sync.tables import event_log
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.identity_contracts import request_digest
from packages.contracts.p0.task_control_contracts import OperationClosureFact
from packages.contracts.p1.build_records import (
    BuildContentRegistration, BuildFixedInputs, BuildObservationRegistration, BuildRunRecord, BuildView,
)
from packages.contracts.p1.build_requests import BUILD_REQUEST_SCHEMA, BuildCommandResult, RequestBuildRequest
from packages.contracts.p1.workspace_git import content_digest

SETTLED_BUILD_CLOSURES = {"closed_unstarted", "ended_reconciled", "safely_stopped"}


def build_operation_digest(operation_id: str, build_run_id: str, input_digest: str) -> str:
    return content_digest(rfc8785.dumps({
        "schema_revision": "p1-build-operation-r1", "operation_id": operation_id,
        "build_run_id": build_run_id, "build_input_digest": input_digest,
    }))


def read_build_intent(connection, operation_id: str):
    require_transaction(connection)
    statement = select(build_runs).where(build_runs.c.operation_id == operation_id)
    row = connection.execute(statement).mappings().one_or_none()
    if row is None:
        raise BuildBoundaryError("build_not_found", status_code=404)
    try:
        record = BuildRunRecord(
            **{key: row[key] for key in (
                "build_run_id", "operation_id", "command_id", "project_id", "task_id", "accepted_task_version",
                "control_revision", "input_validity_revision", "request_digest", "build_input_digest", "accepted_at",
            )}, fixed_inputs=BuildFixedInputs.model_validate(row["fixed_inputs_json"]),
        )
        request = RequestBuildRequest.model_validate(row["request_json"])
        command = get_by_id(connection, row["command_id"])
        result = BuildCommandResult.model_validate(command.result) if command else None
        if (command is None or command.status_code != 202 or result is None or result.outcome != "accepted"
                or result.operation_id != operation_id or result.build_run_id != record.build_run_id
                or result.command_id != record.command_id
                or result.task_id != record.task_id or result.project_id != record.project_id
                or result.version != record.accepted_task_version or result.request_digest != record.request_digest
                or result.control_revision != record.control_revision
                or result.input_validity_revision != record.input_validity_revision
                or result.build_input_digest != record.build_input_digest
                or command.envelope.action != "operation.request"
                or command.envelope.request_schema_revision != BUILD_REQUEST_SCHEMA
                or command.envelope.scope.resource_kind != "task"
                or command.envelope.scope.resource_id != record.task_id
                or command.envelope.scope.project_id != record.project_id
                or command.envelope.request_digest != row["command_request_digest"]
                or command.authorization_decision_id != row["authorization_decision_id"]
                or command.envelope.request_digest != request_digest(command.envelope, request)
                or request.candidate_id != record.fixed_inputs.candidate.candidate_id
                or request.definition != record.fixed_inputs.definition
                or request.input_set_ref != record.fixed_inputs.source_input_set_ref
                or row["input_set_key"] != reference_key(record.project_id, request.input_set_ref)
                or row["expected_task_version"] + 1 != record.accepted_task_version
                or record.request_digest != build_operation_digest(operation_id, record.build_run_id,
                                                                  record.build_input_digest)):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise BuildBoundaryError("build_intent_invalid") from None
    return row, record


def _event_matches(event, record, event_type, schema):
    return (event["command_id"] == record.command_id and event["project_id"] == record.project_id
            and event["aggregate_kind"] == "build" and event["aggregate_id"] == record.build_run_id
            and event["aggregate_version"] == 1 and event["event_type"] == event_type
            and event["schema_version"] == schema)


def read_build_content(connection, record: BuildRunRecord):
    event = connection.execute(select(event_log).where(
        event_log.c.event_id == "build-content-" + record.command_id,
    )).mappings().one_or_none()
    if event is None:
        return None
    try:
        content = BuildContentRegistration.model_validate(event["payload"])
        if (not _event_matches(event, record, "build.content_verified", "p1-build-content-event-r1")
                or content.operation_id != record.operation_id or content.build_input_digest != record.build_input_digest
                or {item.role for item in content.artifacts} != set(record.fixed_inputs.definition.output_roles)):
            raise ValueError
        return content
    except ValueError:
        raise BuildBoundaryError("build_content_record_invalid") from None


def read_build_execution(connection, record: BuildRunRecord):
    events = connection.execute(select(event_log).where(
        event_log.c.aggregate_kind == "build", event_log.c.aggregate_id == record.build_run_id,
        event_log.c.event_type == "build.execution_observed",
    ).limit(129)).mappings().all()
    if len(events) > 128:
        raise BuildBoundaryError("build_observation_scope_too_large")
    entries, superseded = {}, set()
    try:
        for event in events:
            entry = BuildObservationRegistration.model_validate(event["payload"])
            receipt = entry.observation
            if (not _event_matches(event, record, "build.execution_observed", "p1-build-observation-event-r1")
                    or receipt.operation_id != record.operation_id or receipt.request_digest != record.request_digest
                    or receipt.build_input_digest != record.build_input_digest
                    or receipt.observation_id in entries
                    or event["event_id"] != observation_event_id(receipt.observation_id)):
                raise ValueError
            entries[receipt.observation_id] = entry
        for entry in entries.values():
            previous_id = entry.observation.previous_observation_id
            if previous_id is not None:
                previous = entries[previous_id].observation
                if ((previous.closure in SETTLED_BUILD_CLOSURES and (
                        previous.closure != entry.observation.closure or previous.exit_code != entry.observation.exit_code))
                        or previous.observed_at > entry.observation.observed_at
                        or previous.executor_instance_id != entry.observation.executor_instance_id
                        or previous.executor_generation != entry.observation.executor_generation):
                    raise ValueError
                superseded.add(previous_id)
        heads = set(entries) - superseded
        if not entries:
            return None
        if len(heads) != 1:
            raise ValueError
        head, visited = entries[heads.pop()], set()
        cursor = head
        while cursor is not None:
            identity = cursor.observation.observation_id
            if identity in visited:
                raise ValueError
            visited.add(identity)
            previous = cursor.observation.previous_observation_id
            cursor = None if previous is None else entries[previous]
        if len(visited) != len(entries):
            raise ValueError
        return head
    except (ValueError, KeyError):
        raise BuildBoundaryError("build_observation_record_invalid") from None


def observation_event_id(observation_id: str) -> str:
    return "build-observation-" + content_digest(observation_id.encode("utf-8"))[7:]


def build_view(connection, record: BuildRunRecord) -> BuildView:
    content, execution = read_build_content(connection, record), read_build_execution(connection, record)
    state = "accepted"
    if execution is not None:
        receipt = execution.observation
        state = "running" if receipt.closure == "running" else "unknown"
        if receipt.closure in {"closed_unstarted", "safely_stopped"}:
            state = "failed"
        elif receipt.closure == "ended_reconciled":
            if receipt.exit_code != 0:
                state = "failed"
            elif content is not None and _loaded_content_matches(content, receipt):
                state = "succeeded"
    return BuildView(record=record, state=state, content_verified=content is not None, content=content, execution=execution)


def _loaded_content_matches(content, execution):
    loaded = {item.role: item for item in execution.artifacts}
    if set(loaded) != {item.role for item in content.artifacts}:
        return False
    for item in content.artifacts:
        actual = loaded[item.role]
        expected_id = item.manifest_digest if actual.docker_identity_kind == "oci_manifest" else item.config_digest
        if (actual.storage_id != item.storage_id or actual.manifest_digest != item.manifest_digest
                or actual.config_digest != item.config_digest or actual.platform != item.platform
                or actual.loaded_image_id != expected_id):
            return False
    return True


def pending_build_operations(connection, task_id: str) -> tuple[OperationClosureFact, ...]:
    """Caller holds the Task row; raw content alone never closes an accepted intent."""
    require_transaction(connection)
    rows = connection.execute(select(build_runs.c.operation_id).where(
        build_runs.c.task_id == task_id,
    ).limit(129)).all()
    if len(rows) > 128:
        raise BuildBoundaryError("build_operation_scope_too_large")
    pending = []
    for row in rows:
        _, record = read_build_intent(connection, row.operation_id)
        view = build_view(connection, record)
        if view.state in {"failed", "succeeded"}:
            continue
        pending.append(OperationClosureFact(
            operation_ref=EngineeringRef(kind="operation", object_id=record.operation_id,
                                         revision="p1-build-operation-r1", authority="delivery"),
            owner_kind="task", owner_id=task_id, affects_completion=True,
            closure="running" if view.state == "running" else "unknown", effects_recorded=False,
        ))
    return tuple(pending)
