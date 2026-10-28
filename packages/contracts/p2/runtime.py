"""Internal P2 runtime inputs; snapshots do not replace live admission checks."""

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from packages.contracts.p0.core_contracts import RuntimeInput
from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, expect_kind
from packages.contracts.p1.workspace_git import workspace_path
from .workspace_tools import WORKSPACE_TOOL_SCHEMAS
from .workspace_edits import WORKSPACE_EDIT_SCHEMAS
from .workspace_environment import WORKSPACE_ENVIRONMENT_SCHEMAS
from .workspace_builds import WORKSPACE_BUILD_SCHEMAS


Amount = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=8, allow_inf_nan=False)]


class ContextSourceRead(Contract):
    """A bounded excerpt in the ContextPackage's exact source commit."""

    path: str
    digest: Digest
    purpose: Literal["repository_rules", "source", "contract", "decision", "unresolved", "acceptance"]
    start_line: int = Field(default=1, strict=True, ge=1)
    max_lines: int = Field(default=120, strict=True, ge=1, le=160)

    @field_validator("path")
    @classmethod
    def check_path(cls, value):
        return workspace_path(value)


class ContextPackage(Contract):
    """Immutable references and snapshots for one Run, without prompt or history contents."""

    schema_revision: Literal["p2-context-r1"] = "p2-context-r1"
    context_id: Identifier
    context_revision: Identifier
    run_id: Identifier
    input_set_ref: EngineeringRef
    work_item_id: Identifier
    work_item_revision: Revision
    requirement_ref: EngineeringRef
    acceptance_assets_ref: EngineeringRef
    source_ref: EngineeringRef
    baseline_commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    source_reads: tuple[ContextSourceRead, ...] = Field(default=(), max_length=8)
    contract_refs: tuple[EngineeringRef, ...] = Field(default=(), max_length=32)
    decision_refs: tuple[EngineeringRef, ...] = Field(default=(), max_length=32)
    unresolved_refs: tuple[EngineeringRef, ...] = Field(default=(), max_length=32)
    starting_history_ref: EngineeringRef
    tool_names: tuple[Identifier, ...] = Field(default=(), max_length=32)
    permission_revision: Revision
    permission_scopes: tuple[Identifier, ...] = Field(default=(), max_length=32)
    budget_limit: Amount
    budget_currency: Literal["USD", "CNY"]

    @model_validator(mode="after")
    def check_references(self):
        for ref, kind in (
            (self.input_set_ref, "input_set"),
            (self.requirement_ref, "requirement"),
            (self.acceptance_assets_ref, "acceptance_assets"),
            (self.source_ref, "source"),
            (self.starting_history_ref, "history"),
        ):
            expect_kind(ref, kind)
        for ref in self.contract_refs:
            expect_kind(ref, "contract")
        if self.source_ref.revision != self.baseline_commit:
            raise ValueError("baseline_source_commit_mismatch")
        for refs, purpose in ((self.contract_refs, "contract"), (self.decision_refs, "decision"),
                              (self.unresolved_refs, "unresolved")):
            for ref in refs:
                if ref.authority == "source-files" and not any(
                    item.purpose == purpose and item.path == ref.object_id and item.digest == ref.digest
                    and ref.revision == self.baseline_commit for item in self.source_reads
                ):
                    raise ValueError("context_source_reference_unresolved")
        if len(set(self.tool_names)) != len(self.tool_names):
            raise ValueError("duplicate_tool_name")
        if len(set(self.permission_scopes)) != len(self.permission_scopes):
            raise ValueError("duplicate_permission_scope")
        return self


class RunPolicy(Contract):
    """Run limits; the per-request upper bound uses the context budget currency."""

    model_config_id: Identifier
    model_config_revision: Identifier
    model_name: Identifier
    epoch_id: Identifier
    role: Literal["coordinator", "developer", "verifier", "reviewer", "operator"] = "developer"
    instruction_revision: Literal["agent-r1"] = "agent-r1"
    secret_version_ref: EngineeringRef | None = None
    max_requests: int = Field(default=3, strict=True, ge=1, le=12)
    max_duration_seconds: int = Field(default=60, strict=True, ge=1, le=86400)
    max_output_tokens: int = Field(strict=True, ge=1, le=1000000)
    per_request_cost_upper_bound: Amount

    @model_validator(mode="after")
    def check_secret_reference(self):
        if self.secret_version_ref is not None:
            expect_kind(self.secret_version_ref, "secret_version")
        return self


class RuntimeStartRequest(Contract):
    """Internal registration input; durable workflow parameters use RuntimeInput refs."""

    runtime_input: RuntimeInput
    context: ContextPackage
    policy: RunPolicy

    @model_validator(mode="after")
    def check_binding(self):
        runtime_input, context = self.runtime_input, self.context
        if (runtime_input.run_id != context.run_id
                or runtime_input.context_package.object_id != context.context_id
                or runtime_input.context_package.revision != context.context_revision
                or runtime_input.input_set != context.input_set_ref
                or runtime_input.committed_history != context.starting_history_ref):
            raise ValueError("runtime_context_binding_mismatch")
        if self.policy.role != "developer" and (
                {"submit_operation", *WORKSPACE_TOOL_SCHEMAS, *WORKSPACE_EDIT_SCHEMAS,
                 *WORKSPACE_ENVIRONMENT_SCHEMAS, *WORKSPACE_BUILD_SCHEMAS} & set(context.tool_names)):
            raise ValueError("agent_role_tool_not_allowed")
        return self
