"""Read actual human conclusions separately from wait resolution and policy gates."""

from sqlalchemy import select

from modules.collaboration.completion_facts import CompletionInputs
from modules.collaboration.fact_reads import FactReader
from modules.identity.tables import audit_records
from packages.contracts.p0.task_control_contracts import HumanTestCompletionFact
from packages.contracts.p1.task_facts import EvidenceMetadata
from packages.contracts.p1.task_requests import TaskDeclaration


def read_human_fact(
    reader: FactReader, inputs: CompletionInputs, declaration: TaskDeclaration,
) -> HumanTestCompletionFact:
    policy = inputs.policy.metadata if inputs.policy else None
    fields = dict(policy_ref=declaration.human_test_policy_ref,
                  is_completion_gate=policy.is_completion_gate if policy else False,
                  policy_current=bool(policy and inputs.current),
                  skip_allowed=policy.skip_allowed if policy else False)
    key = inputs.row["human_conclusion_key"] if inputs.row else None
    if key is None:
        if policy and policy.is_completion_gate:
            reader.block("human_test_gate_unresolved")
        return HumanTestCompletionFact(**fields)
    record = reader.read(key, "human_conclusion")
    if record is None:
        return HumanTestCompletionFact(**fields)
    conclusion = record.metadata
    evidence = reader.read(conclusion.evidence_ref, "evidence")
    audit = reader.connection.execute(select(
        audit_records.c.caller_kind, audit_records.c.subject_id, audit_records.c.project_id,
        audit_records.c.action, audit_records.c.outcome, audit_records.c.target_json,
    ).where(audit_records.c.decision_id == conclusion.authorization_decision_id)).mappings().one_or_none()
    action = {"passed": "human_test.pass", "changes_requested": "human_test.request_changes",
              "skipped": "human_test.skip"}[conclusion.conclusion]
    authorized = (audit is not None and audit["outcome"] == "allowed" and audit["caller_kind"] == "human"
                  and audit["subject_id"] == conclusion.concluded_by.subject_id
                  and audit["project_id"] == reader.project_id and audit["action"] == action)
    target = audit["target_json"] if audit else None
    authorized = (authorized and isinstance(target, dict) and target.get("project_id") == reader.project_id
                  and target.get("resource_kind") in {"human_test", "human_test_session"}
                  and target.get("resource_id") == conclusion.session_id)
    proof = evidence.metadata if evidence else None
    bound = (isinstance(proof, EvidenceMetadata) and proof.role == "human_test"
             and proof.evidence.input_set_ref == conclusion.input_set_ref
             and proof.evidence.result in {"passed", "failed"}
             and (conclusion.conclusion != "passed" or proof.evidence.result == "passed"))
    if not authorized or not bound:
        reader.block("human_conclusion_not_authorized", conclusion.session_id, "human_test")
        return HumanTestCompletionFact(**fields)
    applicable = (inputs.current and inputs.input_set is not None and inputs.candidate is not None
                  and conclusion.policy_ref == declaration.human_test_policy_ref
                  and conclusion.input_set_ref == inputs.input_set.reference
                  and proof.evidence.subject_ref == inputs.candidate.reference)
    if policy and policy.is_completion_gate:
        if not applicable:
            reader.block("human_test_not_current", conclusion.session_id, "human_test")
        elif conclusion.conclusion == "skipped" and not policy.skip_allowed:
            reader.block("human_skip_not_authorized_by_policy", conclusion.session_id, "human_test")
        elif conclusion.conclusion not in {"passed", "skipped"}:
            reader.block("human_test_gate_unresolved", conclusion.session_id, "human_test")
    return HumanTestCompletionFact(
        **fields, session_id=conclusion.session_id, conclusion=conclusion.conclusion,
        concluded_by=conclusion.concluded_by, concluded_at_utc=conclusion.concluded_at_utc,
        conclusion_evidence_ref=conclusion.evidence_ref, authorized_human_conclusion=True,
        applicable_to_final_input=applicable, skip_reason=conclusion.skip_reason,
    )
