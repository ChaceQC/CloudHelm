"""Export independent P0 decision models; this is not a product API payload."""

import json

from packages.contracts.p0.core_contracts import P0CoreContracts
from packages.contracts.p0.decision_common import Contract, ProtocolRevision
from packages.contracts.p0.delivery_contracts import P0DeliveryContracts
from packages.contracts.p0.emergency_contracts import P0EmergencyContracts
from packages.contracts.p0.engineering_contracts import P0EngineeringContracts
from packages.contracts.p0.identity_contracts import P0IdentityContracts
from packages.contracts.p0.migration_contracts import P0MigrationContracts
from packages.contracts.p0.permit_contracts import P0PermitContracts
from packages.contracts.p0.preview_contracts import P0PreviewContracts
from packages.contracts.p0.resource_contracts import P0ResourceContracts
from packages.contracts.p0.task_control_contracts import P0TaskControlContracts


class P0DecisionContracts(Contract):
    protocol_revision: ProtocolRevision = "p0-decisions-r1"
    engineering: P0EngineeringContracts
    runtime: P0CoreContracts
    identity: P0IdentityContracts
    migrations: P0MigrationContracts
    resources: P0ResourceContracts
    task_control: P0TaskControlContracts
    permits: P0PermitContracts
    preview: P0PreviewContracts
    delivery: P0DeliveryContracts
    emergency: P0EmergencyContracts


def decision_schema() -> dict:
    schema = P0DecisionContracts.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "urn:cloudhelm:p0-decisions:r1"
    schema["description"] = "Independent P0 model collection; not a runtime aggregate or released product protocol."
    return schema


if __name__ == "__main__":
    print(json.dumps(decision_schema(), ensure_ascii=False, indent=2, sort_keys=True))
