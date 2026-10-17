"""Public selection of the fixed reference, never a client-supplied source receipt."""

from pydantic import field_validator

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p1.task_requests import PublicGoal, PublicTitle, TaskBudget
from packages.contracts.p1.task_results import TaskCommandResult


class CreateReferenceTaskRequest(Contract):
    source_operation_id: Identifier
    expected_project_revision: Revision
    title: PublicTitle
    goal: PublicGoal
    budget: TaskBudget

    @field_validator("title", "goal")
    @classmethod
    def check_nonblank(cls, value):
        if not value.strip():
            raise ValueError("task_goal_required")
        return value


class ReferenceTaskResult(Contract):
    task: TaskCommandResult
    input_set_ref: EngineeringRef
