"""Bounded Task and Agent summary, without loading SDK history or prompts."""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, cast, func, select, true
from sqlalchemy.engine import Connection

from database.uow import UnitOfWork
from modules.collaboration.tables import task_declarations, task_wait_conditions, work_items
from modules.identity.actors import Actor
from packages.contracts.p0.identity_contracts import canonical_decimal
from packages.contracts.p2.task_agent import (
    TaskAgentFeeSummary, TaskAgentPolicySummary, TaskAgentRunSummary, TaskAgentSessionSummary,
    TaskAgentSummary, TaskAgentWait, TaskAgentWorkItemSummary,
)
from packages.contracts.p2.tool_protocol import DISPATCH_TOOL_PROTOCOL_REVISION
from .billing_tables import agent_model_request_results
from .operation_tables import agent_operation_waits
from .tables import agent_model_requests, agent_runs, agent_sessions
from .work_item_capabilities import project_work_items_capabilities_in_uow


_SESSION_LIMIT = 8
_RUN_LIMIT = 8
_WORK_ITEM_LIMIT = 32
_WAIT_LIMIT = 8


def _amount(value: Decimal) -> str:
    return canonical_decimal(format(value, "f"))


def _read_sessions(connection: Connection, task_id: str) -> tuple[tuple[TaskAgentSessionSummary, ...], bool]:
    session = agent_sessions.c
    rows = connection.execute(select(session.session_id, session.version, session.state).where(
        session.task_id == task_id,
    ).order_by(session.created_at.desc(), session.session_id.desc()).limit(_SESSION_LIMIT + 1)).mappings().all()
    if not rows:
        return (), False
    truncated = len(rows) > _SESSION_LIMIT
    rows = rows[:_SESSION_LIMIT]
    by_session = {row["session_id"]: [] for row in rows}
    run = agent_runs.c
    context, policy = run.start_json["context"], run.start_json["policy"]
    recent = select(
        run.session_id, run.run_id, run.state, run.request_count, run.reserved_cost,
        run.created_at, run.started_at, run.deadline_at,
        context["work_item_id"].astext.label("work_item_id"),
        cast(context["work_item_revision"].astext, BigInteger).label("work_item_revision"),
        func.coalesce(policy["tool_protocol_revision"].astext, DISPATCH_TOOL_PROTOCOL_REVISION)
        .label("tool_protocol_revision"),
        run.result_json["turn"]["reason_code"].astext.label("reason_code"),
        func.coalesce(policy["role"].astext, "developer").label("role"),
        policy["max_requests"].as_integer().label("max_requests"),
        policy["max_duration_seconds"].as_integer().label("max_duration_seconds"),
        policy["max_output_tokens"].as_integer().label("max_output_tokens"),
        policy["per_request_cost_upper_bound"].astext.label("per_request_cost_upper_bound"),
    ).where(run.session_id == session.session_id).correlate(agent_sessions).order_by(
        run.created_at.desc(), run.run_id.desc(),
    ).limit(_RUN_LIMIT + 1).lateral("recent_agent_runs")
    for row in connection.execute(select(recent).select_from(agent_sessions.join(recent, true())).where(
        session.session_id.in_(list(by_session)),
    ).order_by(recent.c.created_at.desc(), recent.c.run_id.desc())).mappings():
        by_session[row["session_id"]].append(row)

    sessions = []
    for session_row in rows:
        run_rows = by_session[session_row["session_id"]]
        truncated |= len(run_rows) > _RUN_LIMIT
        latest = run_rows[0] if run_rows else None
        sessions.append(TaskAgentSessionSummary(
            session_id=session_row["session_id"], version=session_row["version"], state=session_row["state"],
            work_item_id=latest["work_item_id"] if latest is not None else None,
            policy=TaskAgentPolicySummary(
                role=latest["role"], max_requests=latest["max_requests"],
                max_duration_seconds=latest["max_duration_seconds"], max_output_tokens=latest["max_output_tokens"],
                per_request_cost_upper_bound=_amount(Decimal(latest["per_request_cost_upper_bound"])),
            ) if latest is not None else None,
            runs=tuple(TaskAgentRunSummary(
                run_id=row["run_id"], work_item_id=row["work_item_id"], work_item_revision=row["work_item_revision"],
                state=row["state"], request_count=row["request_count"], reserved_cost=format(row["reserved_cost"], "f"),
                created_at=row["created_at"], started_at=row["started_at"], deadline_at=row["deadline_at"],
                tool_protocol_revision=row["tool_protocol_revision"], reason_code=row["reason_code"],
            ) for row in run_rows[:_RUN_LIMIT]),
        ))
    return tuple(sessions), truncated


def _read_fees(connection: Connection, task: Mapping[str, Any], run_ids: list[str]) -> TaskAgentFeeSummary:
    declaration = task_declarations.c
    currency = select(declaration.declaration_json["budget"]["currency"].astext).where(
        declaration.project_id == task["project_id"], declaration.declaration_id == task["declaration_id"],
    ).scalar_subquery()
    request, observation = agent_model_requests.c, agent_model_request_results.c
    requests = select(request.request_record_id, request.reserved_cost).where(request.run_id.in_(run_ids)).subquery()
    latest = select(observation.calculated_cost).where(
        observation.request_record_id == requests.c.request_record_id,
    ).order_by(observation.revision.desc()).limit(1).lateral("latest_observation")
    unknown = latest.c.calculated_cost.is_(None)
    row = connection.execute(select(
        currency.label("currency"), func.sum(latest.c.calculated_cost).label("known_calculated_cost"),
        func.count().filter(unknown).label("unknown_request_count"),
        func.coalesce(func.sum(requests.c.reserved_cost).filter(unknown), 0).label("unknown_reserved_cost"),
    ).select_from(requests.outerjoin(latest, true()))).mappings().one()
    known = row["known_calculated_cost"]
    return TaskAgentFeeSummary(scope="listed_runs", currency=row["currency"],
        known_calculated_cost=_amount(known) if known is not None else None,
        unknown_request_count=row["unknown_request_count"], unknown_reserved_cost=_amount(row["unknown_reserved_cost"]))


def query_agent_summary_in_uow(
    uow: UnitOfWork, actor: Actor, task: Mapping[str, Any], *, authorization_revision: int,
    engineering_registration, preview_installation,
) -> TaskAgentSummary:
    """Project only persisted facts; the caller authorizes Task and operation reads."""
    connection, task_id = uow.connection, task["task_id"]
    item = work_items.c
    item_rows = connection.execute(select(
        item.work_item_id, item.revision, item.state, item.required, item.goal,
        item.owner_session_id, item.blocked_reason, item.run_requirements_json,
    ).where(item.task_id == task_id).order_by(item.work_item_id).limit(_WORK_ITEM_LIMIT + 1)).mappings().all()
    items = item_rows[:_WORK_ITEM_LIMIT]
    capabilities = project_work_items_capabilities_in_uow(uow, actor, task, items,
        authorization_revision=authorization_revision, engineering_registration=engineering_registration,
        preview_installation=preview_installation)
    sessions, sessions_truncated = _read_sessions(connection, task_id)
    wait, condition = agent_operation_waits.c, task_wait_conditions.c
    waits = connection.execute(select(
        wait.wait_condition_id, wait.from_run_id, wait.tool_call_id, wait.operation_id, condition.state,
        wait.continuation_run_id, condition.required_for_completion,
    ).select_from(task_wait_conditions.join(agent_operation_waits)).where(
        condition.task_id == task_id, condition.state.in_(("waiting", "satisfied")),
        wait.continuation_run_id.is_(None),
    ).order_by(wait.wait_condition_id.desc()).limit(_WAIT_LIMIT + 1)).mappings().all()

    return TaskAgentSummary(task_id=task_id, project_id=task["project_id"], state=task["state"],
        version=task["version"], control_revision=task["control_revision"], input_status=task["input_status"],
        input_validity_revision=task["input_validity_revision"], ordinary_progress_closed=task["ordinary_progress_closed"],
        work_items=tuple(TaskAgentWorkItemSummary(
            work_item_id=row["work_item_id"], revision=row["revision"], state=row["state"], required=row["required"],
            goal=row["goal"], owner_session_id=row["owner_session_id"], blocked_reason=row["blocked_reason"],
            capabilities=capability,
        ) for row, capability in zip(items, capabilities, strict=True)), sessions=sessions,
        waits=tuple(TaskAgentWait(**row) for row in waits[:_WAIT_LIMIT]),
        fees=_read_fees(connection, task, [run.run_id for session in sessions for run in session.runs]),
        truncated=sessions_truncated or len(item_rows) > _WORK_ITEM_LIMIT or len(waits) > _WAIT_LIMIT)
