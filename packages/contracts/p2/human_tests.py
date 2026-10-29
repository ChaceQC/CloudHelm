"""Fixed human-test rounds and explicit human conclusions."""

from datetime import timedelta
from typing import Literal

from pydantic import Field, model_validator

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef, InputSet, UtcTimestamp, expect_kind
from packages.contracts.p0.identity_contracts import Principal
from packages.contracts.p1.task_facts import HumanConclusionMetadata, HumanPolicyMetadata

HUMAN_TEST_SCHEMA = "p2-human-test-r1"
HUMAN_TEST_INITIAL_DURATION = timedelta(hours=4)
HUMAN_TEST_RENEWAL_DURATION = timedelta(hours=2)
HUMAN_TEST_MAX_DURATION = timedelta(hours=6)
HUMAN_TEST_IDLE_DURATION = timedelta(minutes=30)
HUMAN_TEST_IDLE_GRACE = timedelta(minutes=5)
HumanTestState = Literal["preparing", "awaiting_human", "testing", "completed", "expired", "cancelled"]
HumanTestConclusion = Literal["passed", "changes_requested", "skipped"]


class HumanTestVersionGuard(Contract):
    expected_version: Revision
    expected_control_revision: Revision
    expected_input_validity_revision: Revision


class StartHumanTestRequest(HumanTestVersionGuard):
    """An explicit opt-in; fixed facts and the round identity come from the server."""

    candidate_id: Identifier
    tester_id: Identifier
    test_config_ref: EngineeringRef
    dataset_ref: EngineeringRef

    @model_validator(mode="after")
    def check_inputs(self):
        expect_kind(self.test_config_ref, "environment_config", "descriptor")
        expect_kind(self.dataset_ref, "artifact", "descriptor")
        return self


class HumanTestSessionGuard(HumanTestVersionGuard):
    expected_session_revision: Revision


class HumanTestFeedback(Contract):
    summary: str = Field(min_length=1, max_length=4096)
    steps: str | None = Field(default=None, max_length=8192)
    expected: str | None = Field(default=None, max_length=4096)
    actual: str | None = Field(default=None, max_length=4096)
    attachment_refs: tuple[EngineeringRef, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def check_attachments(self):
        for ref in self.attachment_refs:
            expect_kind(ref, "artifact", "evidence")
        return self


class HumanTestConclusionRequest(HumanTestSessionGuard):
    conclusion: HumanTestConclusion
    feedback: HumanTestFeedback | None = None
    skip_reason: Identifier | None = None

    @model_validator(mode="after")
    def check_conclusion(self):
        if (self.conclusion == "skipped") != (self.skip_reason is not None):
            raise ValueError("human_skip_reason_required_only_for_skip")
        if self.conclusion == "changes_requested" and self.feedback is None:
            raise ValueError("human_changes_feedback_required")
        return self


class HumanTestSession(Contract):
    schema_revision: Literal["p2-human-test-r1"] = HUMAN_TEST_SCHEMA
    session_id: Identifier
    command_id: Identifier
    project_id: Identifier
    task_id: Identifier
    round_id: Identifier
    revision: Revision
    task_version: Revision
    control_revision: Revision
    input_validity_revision: Revision
    candidate_id: Identifier
    candidate_ref: EngineeringRef
    verification_report_id: Identifier
    source_input_set_ref: EngineeringRef
    final_input_set_ref: EngineeringRef
    input_set: InputSet
    artifact_refs: tuple[EngineeringRef, ...] = Field(min_length=1, max_length=64)
    requirement_ref: EngineeringRef
    acceptance_assets_ref: EngineeringRef
    policy_ref: EngineeringRef
    policy: HumanPolicyMetadata
    test_config_ref: EngineeringRef
    dataset_ref: EngineeringRef
    tester: Principal
    environment_id: Identifier | None = None
    environment_ref: EngineeringRef | None = None
    state: HumanTestState
    preparation_reason: Identifier | None = None
    wait_condition_id: Identifier | None = None
    entry_authorization_decision_id: Identifier
    access_authorization_decision_id: Identifier | None = None
    created_at: UtcTimestamp
    ready_at: UtcTimestamp | None = None
    expires_at: UtcTimestamp | None = None
    last_human_activity_at: UtcTimestamp | None = None
    idle_warning_at: UtcTimestamp | None = None
    renewed_at: UtcTimestamp | None = None
    ended_at: UtcTimestamp | None = None
    feedback: HumanTestFeedback | None = None
    conclusion: HumanConclusionMetadata | None = None
    conclusion_ref: EngineeringRef | None = None

    @model_validator(mode="after")
    def check_binding(self):
        for ref, kind in (
            (self.candidate_ref, "candidate"), (self.source_input_set_ref, "input_set"),
            (self.final_input_set_ref, "input_set"),
            (self.requirement_ref, "requirement"), (self.acceptance_assets_ref, "acceptance_assets"),
            (self.policy_ref, "policy"),
        ):
            expect_kind(ref, kind)
        for ref in self.artifact_refs:
            expect_kind(ref, "artifact")
        if self.tester.kind != "human":
            raise ValueError("human_test_tester_required")
        if (self.ready_at is None) != (self.expires_at is None):
            raise ValueError("human_test_deadline_requires_ready")
        if self.ready_at is None and (self.last_human_activity_at is not None or self.idle_warning_at is not None
                                      or self.renewed_at is not None or self.wait_condition_id is not None):
            raise ValueError("human_test_not_ready")
        if self.ready_at is not None:
            duration = HUMAN_TEST_MAX_DURATION if self.renewed_at is not None else HUMAN_TEST_INITIAL_DURATION
            if self.expires_at != self.ready_at + duration:
                raise ValueError("human_test_deadline_mismatch")
            if self.renewed_at is not None and not (
                self.ready_at <= self.renewed_at < self.ready_at + HUMAN_TEST_INITIAL_DURATION
            ):
                raise ValueError("human_test_renewal_outside_initial_deadline")
        if self.state in {"awaiting_human", "testing"} and (
            self.ready_at is None or self.environment_id is None or self.wait_condition_id is None
            or self.access_authorization_decision_id is None or self.environment_ref is None
        ):
            raise ValueError("human_test_access_not_ready")
        if self.environment_ref is not None:
            expect_kind(self.environment_ref, "environment")
        if (self.conclusion is None) != (self.conclusion_ref is None):
            raise ValueError("human_test_conclusion_binding_required")
        if (self.state == "completed") != (self.conclusion is not None):
            raise ValueError("human_test_conclusion_binding_required")
        if self.conclusion is not None:
            expect_kind(self.conclusion_ref, "evidence")
            if (self.conclusion.session_id != self.session_id or self.conclusion.policy_ref != self.policy_ref
                    or self.conclusion.input_set_ref != self.final_input_set_ref):
                raise ValueError("human_test_conclusion_binding_mismatch")
        return self


class HumanTestView(Contract):
    """No session means the optional test has not been enabled for this view."""

    session: HumanTestSession | None = None


class HumanTestCommandResult(Contract):
    command_id: Identifier
    session: HumanTestSession
