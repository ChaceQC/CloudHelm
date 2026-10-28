"""Development feedback and handoffs on the existing Run and operation chain."""

from collections import deque

from modules.collaboration.errors import TaskBoundaryError
from modules.workspaces.operations import read_workspace_operation, read_workspace_row
from .operations import _digest, _result_in_uow
from .source_context import safe_context_text


class DevelopmentLoop:
    def __init__(self, max_no_progress_calls):
        self.limit = max_no_progress_calls
        self.repeated = 0
        self.calls = 0
        self.seen = set()
        self.feedback = deque(maxlen=4)

    def observe(self, name, arguments, tool_call_id, result):
        digest = _digest(result)
        feedback = ({key: value for key, value in result.items()
                     if key not in {"started_at", "finished_at", "evidence_digest"}}
                    if name == "workspace.check" else result)
        fingerprint = _digest([name, arguments, feedback])
        self.repeated = self.repeated + 1 if fingerprint in self.seen else 0
        self.seen.add(fingerprint)
        self.calls += 1
        self.feedback.append({"tool": name, "tool_call_id": tool_call_id, "result_digest": digest})

    def stop_reason(self):
        return "agent_no_progress" if self.repeated >= self.limit else None

    def handoff(self, output, stop_reason):
        if output is None and stop_reason is None:
            return None
        return {
            "reason": stop_reason or "agent_" + output.reason,
            "summary": safe_context_text(output.summary) if output else "Run stopped at the recorded boundary.",
            "next_action": safe_context_text(output.next_action) if output else
                "Inspect the committed history, request records and original operations before authorizing another Run.",
            "candidate_operation_id": output.candidate_operation_id if output else None,
            "tool_calls": self.calls, "repeated_feedback_calls": self.repeated,
            "max_no_progress_calls": self.limit, "recent_feedback": list(self.feedback),
        }


def resolve_candidate_handoff_in_uow(uow, run, request, handoff):
    """Model explanations cannot promote an accepted or stale freeze to a delivery."""
    if handoff["reason"] != "agent_candidate_ready":
        return
    operation_id = handoff["candidate_operation_id"]
    intent, _ = read_workspace_operation(uow.connection, operation_id)
    if intent.result.kind != "candidate":
        raise TaskBoundaryError("agent_candidate_operation_required")
    result = _result_in_uow(uow, run["source_command_id"], request, operation_id)
    if result is None:
        raise TaskBoundaryError("agent_candidate_not_ready")
    registration = result["registration"]
    workspace = read_workspace_row(uow.connection, intent.result.workspace_id, for_update=True)
    if (not registration["applicable"] or workspace["binding_json"] != registration["binding_after"]
            or intent.request.input_set_ref != request.context.input_set_ref
            or intent.request.expected_control_revision != request.runtime_input.expected_task_control_revision
            or intent.request.expected_input_validity_revision != request.runtime_input.expected_input_validity_revision):
        raise TaskBoundaryError("agent_candidate_not_current")
    handoff["candidate"] = registration["receipt"]["snapshot"]
    handoff["input_set"] = request.context.input_set_ref.model_dump(mode="json")
