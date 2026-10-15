"""Synchronous Task application commands with one transaction owner per call."""

from dbos import DBOSClient
from sqlalchemy.engine import Engine

from database.commands import CommandConflict
from database.uow import UnitOfWork
from modules.collaboration.command_support import (
    TaskAccessContext, assert_result_read_access, lock_task_access, persist_result,
    prepare_task_command, rejected_result,
)
from modules.collaboration.control_commands import cancel_task, complete_task, reconcile_task
from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.facts import read_completion_report
from modules.collaboration.guards import read_task
from modules.collaboration.input_commands import bind_initial_input_in_uow, invalidate_input, register_write_intent
from modules.collaboration.lifecycle_commands import create_task, start_task
from modules.collaboration.queries import task_view
from modules.collaboration.step_commands import run_step
from modules.identity.actors import Actor, validate_actor
from modules.workflow.version import CONTROL_WORKFLOW, INITIAL_WORKFLOW
from packages.contracts.p0.task_control_contracts import TaskCompletionReport
from packages.contracts.p1.task_internal import (
    BindInitialTaskInputRequest, InvalidateTaskInputRequest, RegisterTaskWriteIntentRequest,
)
from packages.contracts.p1.task_requests import (
    CancelTaskRequest, CompleteTaskRequest, CreateTaskRequest, ReconcileTaskRequest, StartTaskRequest,
)
from packages.contracts.p1.task_results import TaskCommandResult, TaskHttpResult, TaskView


def _validated(request, schema):
    if type(request) is not schema:
        raise TaskBoundaryError("task_request_schema_invalid", status_code=422)
    try:
        return schema.model_validate(request.model_dump(mode="python"))
    except ValueError:
        raise TaskBoundaryError("task_request_schema_invalid", status_code=422) from None


class TaskApplication:
    def __init__(self, engine: Engine, control_engine: Engine, dbos_client: DBOSClient) -> None:
        self.engine = engine
        self.control_engine = control_engine
        self.dbos_client = dbos_client

    def create(self, actor: Actor, project_id: str, request: CreateTaskRequest, *, idempotency_key: str) -> TaskHttpResult:
        request = _validated(request, CreateTaskRequest)
        validate_actor(actor)
        try:
            with UnitOfWork(self.engine) as uow:
                return create_task(uow, actor, project_id, request, idempotency_key)
        except CommandConflict as error:
            raise TaskBoundaryError(str(error)) from None

    def start(self, actor: Actor, task_id: str, request: StartTaskRequest, *, idempotency_key: str) -> TaskHttpResult:
        return self._execute(actor, task_id, request, StartTaskRequest, idempotency_key, self.engine)

    def complete(self, actor: Actor, task_id: str, request: CompleteTaskRequest, *, idempotency_key: str) -> TaskHttpResult:
        return self._execute(actor, task_id, request, CompleteTaskRequest, idempotency_key, self.control_engine)

    def cancel(self, actor: Actor, task_id: str, request: CancelTaskRequest, *, idempotency_key: str) -> TaskHttpResult:
        return self._execute(actor, task_id, request, CancelTaskRequest, idempotency_key, self.control_engine)

    def reconcile(self, actor: Actor, task_id: str, request: ReconcileTaskRequest, *, idempotency_key: str) -> TaskHttpResult:
        return self._execute(actor, task_id, request, ReconcileTaskRequest, idempotency_key, self.control_engine)

    def invalidate_input(self, actor: Actor, task_id: str, request: InvalidateTaskInputRequest, *, idempotency_key: str) -> TaskHttpResult:
        return self._execute(actor, task_id, request, InvalidateTaskInputRequest, idempotency_key, self.control_engine)

    def bind_initial_input(
        self, actor: Actor, task_id: str, request: BindInitialTaskInputRequest, *, idempotency_key: str,
    ) -> TaskHttpResult:
        with UnitOfWork(self.engine) as uow:
            return bind_initial_input_in_uow(uow, actor, task_id, request, idempotency_key=idempotency_key)

    def register_write_intent(self, actor: Actor, task_id: str, request: RegisterTaskWriteIntentRequest, *, idempotency_key: str) -> TaskHttpResult:
        return self._execute(actor, task_id, request, RegisterTaskWriteIntentRequest, idempotency_key, self.engine)

    def _apply(self, context, request):
        if isinstance(request, StartTaskRequest):
            return start_task(context, request, self.dbos_client)
        if isinstance(request, CompleteTaskRequest):
            return complete_task(context, request)
        if isinstance(request, CancelTaskRequest):
            return cancel_task(context, request, self.dbos_client)
        if isinstance(request, ReconcileTaskRequest):
            return reconcile_task(context, request, self.dbos_client)
        if isinstance(request, InvalidateTaskInputRequest):
            return invalidate_input(context, request)
        return register_write_intent(context, request)

    def _execute(self, actor, task_id, request, schema, key, engine):
        request = _validated(request, schema)
        validate_actor(actor)
        try:
            with UnitOfWork(engine) as uow:
                context, existing = prepare_task_command(uow, actor, task_id, request, key)
                if existing is not None:
                    result = TaskCommandResult.model_validate(existing.result)
                    assert_result_read_access(context, result)
                    return TaskHttpResult(status_code=existing.status_code, body=result)
                try:
                    with uow.connection.begin_nested():
                        result, status = self._apply(context, request)
                except TaskBoundaryError as error:
                    context.task = read_task(uow.connection, task_id, for_update=True)
                    result, status = rejected_result(context, error)
                return persist_result(context, result, status)
        except CommandConflict as error:
            raise TaskBoundaryError(str(error)) from None

    def query(self, actor: Actor, task_id: str) -> TaskView:
        validate_actor(actor)
        try:
            with UnitOfWork(self.control_engine) as uow:
                task, authorization = lock_task_access(uow, actor, task_id, "resource.read")
                return task_view(TaskAccessContext(uow, actor, task, authorization))
        except TaskBoundaryError as error:
            raise TaskBoundaryError(error.code, status_code=error.status_code) from None

    def report(self, actor: Actor, task_id: str) -> TaskCompletionReport:
        validate_actor(actor)
        with UnitOfWork(self.control_engine) as uow:
            task, _ = lock_task_access(uow, actor, task_id, "resource.read")
            report = read_completion_report(uow.connection, task)
            if report is None:
                raise TaskBoundaryError("completion_report_not_available")
            return report

    def run_initial(self, command_id: str) -> TaskCommandResult:
        return run_step(self.engine, command_id, INITIAL_WORKFLOW)

    def run_control(self, command_id: str) -> TaskCommandResult:
        return run_step(self.control_engine, command_id, CONTROL_WORKFLOW)
