"""P0 draft of D01 runtime contracts; no product API or P0.3 approval."""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(min_length=1, max_length=160)]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EngineeringRef(Contract):
    kind: Literal["context", "input_set", "history", "messages", "deferred_results", "evidence", "artifact"]
    object_id: Identifier
    revision: Identifier
    digest: Digest


class RuntimeInput(Contract):
    protocol_revision: Literal["p0-draft-r1"] = "p0-draft-r1"
    session_id: Identifier
    run_id: Identifier
    expected_session_version: Annotated[int, Field(ge=0)]
    context_package: EngineeringRef
    input_set: EngineeringRef
    committed_history: EngineeringRef
    pending_messages: EngineeringRef | None = None
    deferred_results: EngineeringRef | None = None


class AcceptedReceipt(Contract):
    operation_id: Identifier
    request_digest: Digest
    status: Literal["accepted"]
    query_ref: EngineeringRef
    wait_ref: EngineeringRef


class TurnResult(Contract):
    run_id: Identifier
    outcome: Literal["tool_requests", "waiting_condition", "submitted", "continue_required"]
    history_delta: EngineeringRef
    request_records: list[Identifier] = Field(default_factory=list, max_length=12)
    tool_request_refs: list[EngineeringRef] = Field(default_factory=list, max_length=8)
    wait_condition_refs: list[EngineeringRef] = Field(default_factory=list, max_length=8)
    delivery_refs: list[EngineeringRef] = Field(default_factory=list, max_length=8)
    reason_code: Identifier


class P0RuntimeContracts(Contract):
    runtime_input: RuntimeInput
    turn_result: TurnResult
    accepted_receipt: AcceptedReceipt


if __name__ == "__main__":
    print(json.dumps(P0RuntimeContracts.model_json_schema(), ensure_ascii=False, indent=2))
