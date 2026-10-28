"""Fresh Task, identity and spending admission for every actual outbound attempt."""

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import case, exists, func, insert, select, update

from database.readiness import assert_runtime_ready
from database.uow import UnitOfWork
from modules.collaboration.command_support import lock_task_access
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_declaration
from modules.collaboration.guards import require_ordinary_progress
from modules.identity.actors import actor_for_command
from packages.contracts.p2.runtime import RuntimeStartRequest
from .billing import model_request_bound_exceeded, model_request_cost
from .tables import agent_model_requests, agent_runs, agent_sessions


def current_run(uow, run_id):
    """Identity/policy -> Task -> Session/Run, in the existing lock order."""
    assert_runtime_ready(uow.connection, role="worker")
    source = uow.connection.execute(select(agent_runs.c.source_command_id).where(
        agent_runs.c.run_id == run_id)).scalar_one()
    actor = actor_for_command(uow, source)
    stored = uow.connection.execute(select(agent_runs.c.start_json).where(
        agent_runs.c.run_id == run_id)).scalar_one()
    request = RuntimeStartRequest.model_validate(stored)
    incoming = request.runtime_input
    task, _ = lock_task_access(uow, actor, incoming.task_id, "task.command")
    require_ordinary_progress(uow.connection, incoming.task_id, expected_version=task["version"],
        expected_control_revision=incoming.expected_task_control_revision,
        expected_input_validity_revision=incoming.expected_input_validity_revision)
    exceeded = uow.connection.scalar(select(exists(select(1).select_from(
        agent_model_requests.join(agent_runs).join(agent_sessions)).where(
        agent_sessions.c.task_id == incoming.task_id, model_request_bound_exceeded()))))
    if exceeded:
        raise TaskBoundaryError("model_reservation_bound_exceeded")
    session = uow.connection.execute(select(agent_sessions).where(
        agent_sessions.c.session_id == incoming.session_id).with_for_update()).mappings().one()
    run = uow.connection.execute(select(agent_runs).where(
        agent_runs.c.run_id == run_id).with_for_update()).mappings().one()
    if (session["version"] != incoming.expected_session_version
            or session["task_id"] != incoming.task_id or run["state"] not in {"queued", "running"}):
        raise TaskBoundaryError("agent_run_not_current")
    now = uow.connection.scalar(select(func.clock_timestamp()))
    if run["deadline_at"] is not None and now >= run["deadline_at"]:
        raise TaskBoundaryError("agent_run_deadline_exceeded")
    return task, session, run, request, now


class RuntimeAdmission:
    def __init__(self, engine, run_id):
        self.engine, self.run_id = engine, run_id

    async def model_request(self, body_digest: str, body_bytes: int) -> str:
        with UnitOfWork(self.engine) as uow:
            task, _, run, request, _ = current_run(uow, self.run_id)
            policy, context = request.policy, request.context
            declaration = read_declaration(uow.connection, task)
            if run["request_count"] >= policy.max_requests:
                raise TaskBoundaryError("agent_request_limit")
            # Fixed P0 global Standard text/functions profile, using its larger long
            # input/cache-write and output rates. No cache discount or known charge.
            required = (Decimal(body_bytes + 8192) * Decimal("0.25")
                        + Decimal(policy.max_output_tokens) * Decimal("0.75")) / Decimal(1000000)
            bound = policy.per_request_cost_upper_bound
            if bound < required:
                raise TaskBoundaryError("model_reservation_bound_insufficient")
            cost = model_request_cost()
            spent, run_spent = uow.connection.execute(select(
                func.coalesce(func.sum(cost), 0),
                func.coalesce(func.sum(case((agent_model_requests.c.run_id == self.run_id, cost), else_=0)), 0))
                .select_from(agent_model_requests.join(agent_runs).join(agent_sessions))
                .where(agent_sessions.c.task_id == task["task_id"])).one()
            if (context.budget_currency != "USD" or declaration.budget.currency != "USD"
                    or run_spent + bound > context.budget_limit
                    or spent + bound > Decimal(declaration.budget.amount)):
                raise TaskBoundaryError("model_budget_exhausted")
            record_id = "request-" + uuid4().hex
            uow.connection.execute(insert(agent_model_requests).values(
                request_record_id=record_id, run_id=self.run_id,
                request_sequence=run["request_count"] + 1, body_digest=body_digest,
                body_bytes=body_bytes, reserved_cost=bound, state="unknown"))
            uow.connection.execute(update(agent_runs).where(agent_runs.c.run_id == self.run_id).values(
                request_count=run["request_count"] + 1, reserved_cost=run["reserved_cost"] + bound))
        return record_id

    async def tool(self, name: str) -> None:
        with UnitOfWork(self.engine) as uow:
            _, _, _, request, _ = current_run(uow, self.run_id)
            if (name not in request.context.tool_names
                    or name not in {"task.read", "submit_operation", "query_operation", "await_operation"}):
                raise TaskBoundaryError("agent_tool_not_allowed")

    def begin(self):
        with UnitOfWork(self.engine) as uow:
            task, session, run, request, now = current_run(uow, self.run_id)
            # A missing step checkpoint cannot prove that an admitted request was
            # unsent. Preserve the original Run and its reservations for reconciliation.
            if run["request_count"]:
                raise TaskBoundaryError("model_request_reconciliation_required")
            if run["started_at"] is None:
                uow.connection.execute(update(agent_runs).where(agent_runs.c.run_id == self.run_id).values(
                    state="running", started_at=now,
                    deadline_at=now + timedelta(seconds=request.policy.max_duration_seconds)))
                uow.connection.execute(update(agent_sessions).where(
                    agent_sessions.c.session_id == session["session_id"]).values(state="running"))
            deadline = run["deadline_at"] or now + timedelta(seconds=request.policy.max_duration_seconds)
            return request, read_declaration(uow.connection, task).goal, deadline
