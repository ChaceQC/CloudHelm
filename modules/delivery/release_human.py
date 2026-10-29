"""Release policy does not fabricate or require a Task completion report."""

from modules.collaboration.errors import TaskBoundaryError
from modules.collaboration.records import read_fact_source, read_registered_reference
from packages.contracts.p1.task_facts import HumanPolicyMetadata


def check_release_human(connection, task, declaration, candidate_ref):
    policy = read_registered_reference(connection, task["project_id"], declaration.human_test_policy_ref)
    if (not isinstance(policy.metadata, HumanPolicyMetadata)
            or read_fact_source(connection, task["project_id"], policy.source_id).purpose != "product"):
        raise TaskBoundaryError("release_human_policy_invalid")
    from sqlalchemy import select
    from modules.integration.human_test_tables import human_test_sessions
    from packages.contracts.p2.human_tests import HumanTestSession

    latest = connection.scalar(select(human_test_sessions.c.record_json).where(
        human_test_sessions.c.task_id == task["task_id"],
        human_test_sessions.c.record_json["candidate_ref"]["object_id"].astext == candidate_ref.object_id,
    ).order_by(human_test_sessions.c.created_at.desc()).limit(1))
    if latest is not None:
        session = HumanTestSession.model_validate(latest)
        if (session.candidate_ref != candidate_ref or session.conclusion is None
                or session.conclusion.conclusion not in {"passed", "skipped"}
                or session.conclusion.conclusion == "skipped" and not session.policy.skip_allowed):
            raise TaskBoundaryError("release_human_test_pending")
    if not policy.metadata.is_completion_gate and latest is None:
        return
    from modules.collaboration.fact_reads import FactReader
    from modules.collaboration.completion_facts import read_completion_inputs
    from modules.collaboration.human_facts import read_human_fact

    reader = FactReader(connection, task["project_id"], task["task_id"])
    inputs = read_completion_inputs(reader, task, declaration)
    if latest is not None and inputs.row is not None:
        from dataclasses import replace
        from modules.collaboration.records import reference_key

        inputs = replace(inputs, row={**inputs.row,
            "human_conclusion_key": reference_key(task["project_id"], session.conclusion_ref)})
    human = read_human_fact(reader, inputs, declaration)
    satisfied = (inputs.current and inputs.candidate.reference == candidate_ref and human.policy_current
        and human.applicable_to_final_input and (human.conclusion == "passed"
            or human.conclusion == "skipped" and human.skip_allowed))
    if not satisfied:
        raise TaskBoundaryError("release_human_test_pending")
