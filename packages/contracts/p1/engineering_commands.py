"""Internal durable handoffs for the three P1.2 engineering domains."""

from typing import Literal

from pydantic import model_validator

from packages.contracts.p0.decision_common import Contract, Digest, Identifier, Revision

EngineeringWorkflowName = Literal[
    "projects.source_import.v1", "workspaces.operation.v1", "delivery.build.v1",
    "workspaces.development_environment.v1",
    "workspaces.preview.v1",
    "delivery.deployment_stage.v1",
    "integration.merge_queue.v1",
]


class EngineeringWorkflowDispatch(Contract):
    """Only an operation identity enters DBOS; payloads stay in their owning store."""

    command_id: Identifier
    operation_id: Identifier
    workflow_id: Identifier
    business_kind: Literal["project", "workspace", "build", "deployment"]
    business_id: Identifier
    advance_revision: Revision
    workflow_name: EngineeringWorkflowName
    request_digest: Digest

    @model_validator(mode="after")
    def check_domain(self):
        expected = {
            "projects.source_import.v1": "project",
            "workspaces.operation.v1": "workspace",
            "workspaces.development_environment.v1": "workspace",
            "workspaces.preview.v1": "workspace",
            "delivery.build.v1": "build",
            "delivery.deployment_stage.v1": "deployment",
            "integration.merge_queue.v1": "project",
        }
        if self.business_kind != expected[self.workflow_name]:
            raise ValueError("engineering_workflow_domain_mismatch")
        if self.workflow_id != "engineering-" + self.operation_id:
            raise ValueError("engineering_workflow_identity_mismatch")
        return self
