"""Public preview lifecycle commands carry identities, never target addresses."""

from pydantic import Field

from packages.contracts.p0.decision_common import Contract, Identifier, Revision
from packages.contracts.p0.engineering_contracts import EngineeringRef
from packages.contracts.p0.preview_contracts import ClientRouteName
from packages.contracts.p2.human_tests import HumanTestVersionGuard


class StartCandidatePreviewRequest(HumanTestVersionGuard):
    candidate_id: Identifier


class AttachDevelopmentPreviewRequest(HumanTestVersionGuard):
    prepare_operation_id: Identifier


class PreviewEnvironmentControlRequest(HumanTestVersionGuard):
    expected_environment_revision: Revision


class PreviewEnvironmentView(Contract):
    environment_id: Identifier
    purpose: str
    state: str
    actual_revision: str | None = None
    resource_reservation_id: Identifier | None = None
    expires_at: str
    reason: str | None = None
    revocation_status: str | None = None
    management_start_url: str | None = None
    entry_origin: str | None = None
    client_route: ClientRouteName | None = None


class PreviewEnvironmentResult(Contract):
    command_id: Identifier
    environment: PreviewEnvironmentView


class HumanTestOption(Contract):
    candidate_id: Identifier
    label: str
    test_config_ref: EngineeringRef
    dataset_ref: EngineeringRef


class HumanTestOptions(Contract):
    candidates: tuple[HumanTestOption, ...] = Field(default=(), max_length=128)
    tester_id: Identifier
    management_start_url: str | None = None
