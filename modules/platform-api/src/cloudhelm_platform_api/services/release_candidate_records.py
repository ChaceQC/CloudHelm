"""ReleaseCandidate 三表记录与创建事件的原子构造。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.models.workflow_job import WorkflowJob
from cloudhelm_platform_api.repositories.approval_repository import (
    ApprovalRepository,
)
from cloudhelm_platform_api.repositories.release_candidate_repository import (
    ReleaseCandidateRepository,
)
from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)
from cloudhelm_platform_api.services.database_errors import (
    database_write_error,
)
from cloudhelm_platform_api.services.event_service import EventService
from cloudhelm_platform_api.services.release_candidate_policy import (
    APPROVAL_ACTION,
    APPROVAL_TTL,
    RECONCILE_JOB_TYPE,
    ReleaseCandidateIdentity,
    build_reconcile_job_spec,
)


@dataclass(frozen=True)
class CreatedReleaseCandidateRecords:
    """Candidate create 事务内的三个权威资源。"""

    candidate: ReleaseCandidate
    approval: ApprovalRequest
    workflow_job: WorkflowJob


class ReleaseCandidateRecordFactory:
    """预生成 Candidate UUID，并按 Approval→Candidate→Job 顺序落库。"""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.approvals = ApprovalRepository(session)
        self.candidates = ReleaseCandidateRepository(session)
        self.workflow_jobs = WorkflowJobRepository(session)
        self.events = EventService(session)

    def create(
        self,
        *,
        task,
        binding,
        pull_request,
        identity: ReleaseCandidateIdentity,
        database_now: datetime,
    ) -> CreatedReleaseCandidateRecords:
        """构造三表与两类事件；约束异常统一脱敏为 database_error。"""

        candidate_id = uuid4()
        try:
            approval = self.approvals.create(
                ApprovalRequest(
                    task_id=task.id,
                    action=APPROVAL_ACTION,
                    risk_level="L2",
                    reason="批准候选发布身份，供后续受控 ref 与 CI 流程使用。",
                    resource_type="release_candidate",
                    resource_id=candidate_id,
                    request_hash=identity.request_hash,
                    status="pending",
                    requested_by_agent_run_id=(
                        pull_request.created_by_agent_run_id
                    ),
                    expires_at=database_now + APPROVAL_TTL,
                    created_at=database_now,
                )
            )
            candidate = self.candidates.create(
                ReleaseCandidate(
                    id=candidate_id,
                    task_id=task.id,
                    project_id=task.project_id,
                    pull_request_record_id=pull_request.id,
                    repository_binding_id=binding.id,
                    binding_snapshot_json=identity.public_snapshot,
                    binding_snapshot_sha256=(
                        identity.binding_snapshot_sha256
                    ),
                    commit_sha=pull_request.commit_sha,
                    target_ref=identity.target_ref,
                    request_hash=identity.request_hash,
                    approval_id=approval.id,
                    status="pending_approval",
                    idempotency_key=identity.idempotency_key,
                    created_at=database_now,
                    updated_at=database_now,
                )
            )
            job_spec = build_reconcile_job_spec(
                candidate_id=candidate.id,
                approval_id=approval.id,
                pull_request_record_id=pull_request.id,
                candidate_request_hash=identity.request_hash,
                binding_snapshot_sha256=(
                    identity.binding_snapshot_sha256
                ),
            )
            workflow_job = self.workflow_jobs.create(
                WorkflowJob(
                    task_id=task.id,
                    job_type=RECONCILE_JOB_TYPE,
                    resource_type="release_candidate",
                    resource_id=candidate.id,
                    side_effect_class="none",
                    request_hash=job_spec.request_hash,
                    idempotency_key=job_spec.idempotency_key,
                    status="pending",
                    attempt=0,
                    max_attempts=3,
                    enqueue_attempt=0,
                    payload_json=job_spec.payload,
                    created_at=database_now,
                    updated_at=database_now,
                )
            )
            self._record_events(
                candidate=candidate,
                approval=approval,
                workflow_job=workflow_job,
            )
        except IntegrityError as exc:
            self.session.rollback()
            raise database_write_error(exc) from exc
        return CreatedReleaseCandidateRecords(
            candidate=candidate,
            approval=approval,
            workflow_job=workflow_job,
        )

    def _record_events(
        self,
        *,
        candidate: ReleaseCandidate,
        approval: ApprovalRequest,
        workflow_job: WorkflowJob,
    ) -> None:
        """写入不含 profile、clone URL 或 credential 的精确 payload。"""

        common = {
            "candidate_id": str(candidate.id),
            "approval_id": str(approval.id),
            "workflow_job_id": str(workflow_job.id),
            "pull_request_record_id": str(
                candidate.pull_request_record_id
            ),
            "repository_binding_id": str(
                candidate.repository_binding_id
            ),
            "binding_snapshot_sha256": (
                candidate.binding_snapshot_sha256
            ),
            "candidate_request_hash": candidate.request_hash,
        }
        self.events.record(
            "WorkflowJobQueued",
            "system",
            "release-candidate",
            {
                **common,
                "job_type": workflow_job.job_type,
                "job_request_hash": workflow_job.request_hash,
                "status": workflow_job.status,
            },
            candidate.task_id,
        )
        self.events.record(
            "ReleaseCandidateApprovalRequested",
            "system",
            str(approval.requested_by_agent_run_id),
            {
                **common,
                "action": approval.action,
                "risk_level": approval.risk_level,
                "status": candidate.status,
            },
            candidate.task_id,
        )
