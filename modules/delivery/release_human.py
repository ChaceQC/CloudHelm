"""Release policy does not fabricate or require a Task completion report."""

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.records import read_fact_source, read_registered_reference
from packages.contracts.p1.task_facts import HumanPolicyMetadata


def check_release_human(connection, task, declaration, candidate):
    policy = read_registered_reference(connection, task["project_id"], declaration.human_test_policy_ref)
    if (not isinstance(policy.metadata, HumanPolicyMetadata)
            or read_fact_source(connection, task["project_id"], policy.source_id).purpose != "product"):
        raise TaskBoundaryError("release_human_policy_invalid")
    if not policy.metadata.is_completion_gate:
        return
    from modules.collaboration.fact_reads import FactReader
    from modules.collaboration.completion_facts import read_completion_inputs
    from modules.collaboration.human_facts import read_human_fact

    reader = FactReader(connection, task["project_id"], task["task_id"])
    inputs = read_completion_inputs(reader, task, declaration)
    human = read_human_fact(reader, inputs, declaration)
    satisfied = (inputs.current and inputs.candidate.reference == candidate.reference and human.policy_current
        and human.applicable_to_final_input and (human.conclusion == "passed"
            or human.conclusion == "skipped" and human.skip_allowed))
    if not satisfied:
        raise TaskBoundaryError("release_human_test_pending")
