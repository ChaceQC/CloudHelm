"""Worker-only registration of the two bounded Task business workflows."""

from dbos import DBOS, WorkflowSerializationFormat

from modules.collaboration.application import TaskApplication
from packages.contracts.p1.commands import contract_payload

_application: TaskApplication | None = None


def _configured() -> TaskApplication:
    if _application is None:
        raise RuntimeError("task_workflows_not_configured")
    return _application


@DBOS.step(name="collaboration.task_initial.apply.v1", retries_allowed=False)
def _initial_step(command_id: str):
    return contract_payload(_configured().run_initial(command_id))


@DBOS.step(name="collaboration.task_control.apply.v1", retries_allowed=False)
def _control_step(command_id: str):
    return contract_payload(_configured().run_control(command_id))


@DBOS.workflow(name="collaboration.task_initial.v1", serialization_type=WorkflowSerializationFormat.PORTABLE,
               max_recovery_attempts=3)
def task_initial(command_id: str):
    return _initial_step(command_id)


@DBOS.workflow(name="collaboration.task_control.v1", serialization_type=WorkflowSerializationFormat.PORTABLE,
               max_recovery_attempts=3)
def task_control(command_id: str):
    return _control_step(command_id)


def register_task_workflows(application: TaskApplication) -> None:
    """Call once on the worker, after DBOS construction and before launch."""
    global _application
    if not isinstance(application, TaskApplication):
        raise TypeError("task_application_required")
    if _application is not None and _application is not application:
        raise RuntimeError("task_workflows_already_configured")
    _application = application
