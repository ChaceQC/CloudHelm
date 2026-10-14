"""Public Task declarations and command inputs; trusted facts are never API inputs."""

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind
from packages.contracts.p0.identity_contracts import canonical_decimal

TASK_API_SCHEMA_REVISION = "p1-task-api-r1"
PublicTitle = Annotated[str, Field(min_length=1, max_length=160)]
PublicGoal = Annotated[str, Field(min_length=1, max_length=4096)]
BudgetAmount = Annotated[
    str, Field(pattern=r"^(0|[1-9][0-9]{0,15})(\.[0-9]{1,8})?$", max_length=25),
]


class TaskBudget(Contract):
    """A declared spending ceiling, not a reservation or a known actual charge."""

    amount: BudgetAmount
    currency: Literal["USD", "CNY"]

    @field_validator("amount")
    @classmethod
    def normalize_amount(cls, value: str) -> str:
        return canonical_decimal(value)


class TaskDeclaration(Contract):
    title: PublicTitle
    goal: PublicGoal
    requirement_ref: EngineeringRef
    acceptance_assets_ref: EngineeringRef
    source_ref: EngineeringRef
    budget: TaskBudget
    resource_scope_ref: EngineeringRef
    human_test_policy_ref: EngineeringRef

    @model_validator(mode="after")
    def check_references(self):
        for field, kind in (
            ("requirement_ref", "requirement"),
            ("acceptance_assets_ref", "acceptance_assets"),
            ("source_ref", "source"),
            ("resource_scope_ref", "policy"),
            ("human_test_policy_ref", "policy"),
        ):
            expect_kind(getattr(self, field), kind)
        commit = self.source_ref.revision
        if len(commit) not in {40, 64} or any(char not in "0123456789abcdef" for char in commit):
            raise ValueError("full_source_commit_required")
        if not self.title.strip() or not self.goal.strip():
            raise ValueError("task_goal_required")
        return self


class CreateTaskRequest(Contract):
    expected_project_revision: Revision
    declaration: TaskDeclaration


class StartTaskRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision


class CompleteTaskRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision


class CancelTaskRequest(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    cancel_reason: Identifier


class ReconcileTaskRequest(Contract):
    """Reinspect existing facts; this does not authorize new physical operations."""

    expected_version: Revision
    expected_control_revision: Revision
    purpose: Literal["completion", "cancellation"]


TaskCommandRequest = (
    CreateTaskRequest | StartTaskRequest | CompleteTaskRequest
    | CancelTaskRequest | ReconcileTaskRequest
)
