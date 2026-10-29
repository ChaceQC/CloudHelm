"""Bounded code observations from the exact fixed workspace candidate."""

from types import SimpleNamespace

from modules.agent_runtime.code_reading import read_workspace_code
from modules.workspaces.safe_paths import WorkspaceFileError


def read_candidate_code(runtime, build_record, name, query):
    names = {
        "candidate.list_directory": "workspace.list_directory",
        "candidate.read_file": "workspace.read_file",
    }
    if name not in names:
        raise WorkspaceFileError("agent_verification_candidate_tool_unknown")
    candidate = build_record.fixed_inputs.candidate
    if candidate.candidate_id.startswith("integration-candidate-"):
        raise WorkspaceFileError("agent_verification_candidate_source_unsupported")

    with runtime.registry.admit(0) as storage:
        intent = runtime._intent(candidate.freeze_operation_id)
        with runtime._git(storage, candidate.binding.project_id) as git:
            store = runtime._candidate_store(storage, git, intent, reconciliation=True)
            try:
                with store.open_candidate(candidate.freeze_operation_id) as (receipt, files):
                    if receipt.snapshot != candidate:
                        raise WorkspaceFileError("agent_verification_candidate_receipt_mismatch")
                    request = SimpleNamespace(**query.model_dump(), expected_manifest_digest=candidate.manifest_digest)
                    result = read_workspace_code(files, candidate.binding, names[name], request)
                    result.pop("binding")
                    return {**result, "candidate_id": candidate.candidate_id,
                            "candidate_commit": candidate.candidate_commit}
            finally:
                store.close()
