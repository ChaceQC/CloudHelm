"""M7-2D CIRun、Deployment 与 ServiceInstance 测试夹具。"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.base import utc_now
from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.approval import ApprovalRequest
from cloudhelm_platform_api.models.artifact import Artifact
from cloudhelm_platform_api.models.ci_run import CIRun
from cloudhelm_platform_api.models.deployment import Deployment
from cloudhelm_platform_api.models.environment import Environment
from cloudhelm_platform_api.models.release_candidate import ReleaseCandidate
from cloudhelm_platform_api.models.remote_target import RemoteTarget
from cloudhelm_platform_api.models.service_instance import ServiceInstance

from m7_release_job_fixture import (
    build_release_candidate,
    seed_m7_candidate_dependencies,
)

COMMIT_SHA = "1" * 40
IMAGE_DIGEST = "sha256:" + ("a" * 64)
PLATFORM_DIGEST = "sha256:" + ("b" * 64)
REQUEST_HASH = "sha256:" + ("c" * 64)


@dataclass(frozen=True)
class M7CIDeploymentFixture:
    """M7-2D 三表所需的真实父资源引用。"""

    task_id: UUID
    project_id: UUID
    pull_request_record_id: UUID
    release_candidate_id: UUID
    ci_manifest_artifact_id: UUID
    release_plan_artifact_id: UUID
    rollback_request_artifact_id: UUID
    environment_id: UUID
    remote_target_id: UUID
    deployment_approval_id: UUID
    historical_deployment_id: UUID
    historical_deployment_approval_id: UUID
    requester_agent_run_id: UUID
    deployment_id: UUID
    now: datetime


def seed_m7_ci_deployment_dependencies() -> M7CIDeploymentFixture:
    """创建 published Candidate、Artifacts、Environment、Target 和 L3 Approval。"""

    references = seed_m7_candidate_dependencies(pull_request_count=1)
    now = utc_now()
    deployment_id = uuid4()
    historical_deployment_id = uuid4()
    with Session(get_engine(), expire_on_commit=False) as session:
        release_approval = session.get(
            ApprovalRequest,
            references["approval_id"],
        )
        assert release_approval is not None
        release_approval.status = "approved"
        release_approval.decided_by = "reviewer"
        release_approval.decided_at = now
        release_approval.consumed_at = now

        candidate = build_release_candidate(
            references,
            status="published",
            commit_sha=COMMIT_SHA,
            remote_verified_sha=COMMIT_SHA,
            approved_at=now,
            published_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(candidate)

        ci_manifest = _artifact(
            task_id=references["task_id"],
            artifact_type="ci_manifest",
            suffix=uuid4().hex,
        )
        release_plan = _artifact(
            task_id=references["task_id"],
            artifact_type="release_plan",
            suffix=uuid4().hex,
        )
        rollback_request = _artifact(
            task_id=references["task_id"],
            artifact_type="rollback_request",
            suffix=uuid4().hex,
        )
        environment = Environment(
            project_id=references["project_id"],
            name=f"staging-{uuid4().hex[:8]}",
            environment_type="staging",
            status="active",
            base_url="https://staging.example.test",
        )
        session.add_all(
            [
                ci_manifest,
                release_plan,
                rollback_request,
                environment,
            ]
        )
        session.flush()
        target = RemoteTarget(
            environment_id=environment.id,
            display_name="M7-2D Target",
            target_type="linux_remote_agent",
            agent_id=f"remote-{uuid4().hex[:12]}",
            agent_endpoint="https://agent.example.test:9443",
            credential_ref=f"test/m7-2d/{uuid4().hex}",
            tls_fingerprint="sha256:" + ("d" * 64),
            status="online",
            capabilities_json=["heartbeat", "deployment"],
            last_heartbeat_at=now,
            last_status_changed_at=now,
        )
        session.add(target)
        session.flush()
        deployment_approval = _deployment_approval(
            task_id=references["task_id"],
            resource_id=deployment_id,
            requester_agent_run_id=references["creator_agent_run_id"],
            now=now,
        )
        historical_deployment_approval = _deployment_approval(
            task_id=references["task_id"],
            resource_id=historical_deployment_id,
            requester_agent_run_id=references["creator_agent_run_id"],
            now=now,
        )
        session.add_all(
            [
                deployment_approval,
                historical_deployment_approval,
            ]
        )
        session.commit()
        return M7CIDeploymentFixture(
            task_id=references["task_id"],
            project_id=references["project_id"],
            pull_request_record_id=references["pull_request_record_id"],
            release_candidate_id=candidate.id,
            ci_manifest_artifact_id=ci_manifest.id,
            release_plan_artifact_id=release_plan.id,
            rollback_request_artifact_id=rollback_request.id,
            environment_id=environment.id,
            remote_target_id=target.id,
            deployment_approval_id=deployment_approval.id,
            historical_deployment_id=historical_deployment_id,
            historical_deployment_approval_id=(
                historical_deployment_approval.id
            ),
            requester_agent_run_id=references["creator_agent_run_id"],
            deployment_id=deployment_id,
            now=now,
        )


def build_ci_run(
    references: M7CIDeploymentFixture,
    **overrides: Any,
) -> CIRun:
    """构造默认合法的 triggered CIRun。"""

    values: dict[str, Any] = {
        "task_id": references.task_id,
        "project_id": references.project_id,
        "pull_request_record_id": references.pull_request_record_id,
        "release_candidate_id": references.release_candidate_id,
        "provider": "gitea",
        "repository_external_id": "repo-m7-2d",
        "external_run_id": None,
        "external_job_id": None,
        "workflow_id": ".gitea/workflows/cloudhelm-release.yml",
        "workflow_revision": "workflow-v1",
        "source_ref": (
            "refs/heads/cloudhelm/release-candidates/"
            f"{references.release_candidate_id.hex}"
        ),
        "commit_sha": COMMIT_SHA,
        "status": "triggered",
        "idempotency_key": f"ci:{references.release_candidate_id}",
        "created_at": references.now,
        "updated_at": references.now,
    }
    values.update(overrides)
    return CIRun(**values)


def build_passed_ci_run(
    references: M7CIDeploymentFixture,
    **overrides: Any,
) -> CIRun:
    """构造具有真实 run identity 与制品证据的 passed CIRun。"""

    values: dict[str, Any] = {
        "external_run_id": f"run-{references.release_candidate_id.hex}",
        "provider_head_sha": COMMIT_SHA,
        "artifact_manifest_id": references.ci_manifest_artifact_id,
        "image_index_digest": IMAGE_DIGEST,
        "platform_manifest_digest": PLATFORM_DIGEST,
        "status": "passed",
        "started_at": references.now,
        "finished_at": references.now + timedelta(seconds=1),
        "updated_at": references.now + timedelta(seconds=1),
    }
    values.update(overrides)
    return build_ci_run(references, **values)


def build_deployment(
    references: M7CIDeploymentFixture,
    *,
    ci_run_id: UUID,
    **overrides: Any,
) -> Deployment:
    """构造默认合法的 planned Deployment。"""

    deployment_id = overrides.pop("id", references.deployment_id)
    values: dict[str, Any] = {
        "id": deployment_id,
        "task_id": references.task_id,
        "project_id": references.project_id,
        "environment_id": references.environment_id,
        "remote_target_id": references.remote_target_id,
        "ci_run_id": ci_run_id,
        "release_plan_artifact_id": references.release_plan_artifact_id,
        "commit_sha": COMMIT_SHA,
        "image_ref": f"registry.example.test/sample@{IMAGE_DIGEST}",
        "image_digest": IMAGE_DIGEST,
        "platform_manifest_digest": PLATFORM_DIGEST,
        "release_version": "0.6.0-rc.1",
        "request_hash": REQUEST_HASH,
        "approval_id": None,
        "remote_operation_id": None,
        "status": "planned",
        "health_summary_json": None,
        "failure_code": None,
        "failure_summary": None,
        "requested_by_actor": "agent:release",
        "approved_by_actor": None,
        "dispatched_by_agent_run_id": None,
        "idempotency_key": f"deployment:{deployment_id}",
        "started_at": None,
        "finished_at": None,
        "rollback_candidate_id": None,
        "rollback_request_artifact_id": None,
        "created_at": references.now,
        "updated_at": references.now,
    }
    values.update(overrides)
    return Deployment(**values)


def build_healthy_deployment(
    references: M7CIDeploymentFixture,
    *,
    ci_run_id: UUID,
    **overrides: Any,
) -> Deployment:
    """构造经批准、执行并完成健康验证的 Deployment。"""

    values: dict[str, Any] = {
        "approval_id": references.deployment_approval_id,
        "approved_by_actor": "reviewer",
        "remote_operation_id": f"operation-{references.deployment_id.hex}",
        "status": "healthy",
        "health_summary_json": {
            "status": "ok",
            "http_status": 200,
        },
        "started_at": references.now,
        "finished_at": references.now + timedelta(seconds=1),
        "updated_at": references.now + timedelta(seconds=1),
    }
    values.update(overrides)
    return build_deployment(
        references,
        ci_run_id=ci_run_id,
        **values,
    )


def build_service_instance(
    references: M7CIDeploymentFixture,
    *,
    deployment_id: UUID,
    **overrides: Any,
) -> ServiceInstance:
    """构造默认合法的 starting ServiceInstance。"""

    values: dict[str, Any] = {
        "deployment_id": deployment_id,
        "environment_id": references.environment_id,
        "remote_target_id": references.remote_target_id,
        "service_name": "sample-api",
        "compose_project": "cloudhelm-sample-api-staging",
        "runtime_type": "docker_compose",
        "runtime_ref": None,
        "image_digest": IMAGE_DIGEST,
        "status": "starting",
        "health_url": None,
        "health_result_json": None,
        "last_health_check_at": None,
        "last_error_code": None,
        "created_at": references.now,
        "updated_at": references.now,
    }
    values.update(overrides)
    return ServiceInstance(**values)


def _deployment_approval(
    *,
    task_id: UUID,
    resource_id: UUID,
    requester_agent_run_id: UUID,
    now: datetime,
) -> ApprovalRequest:
    """构造 approved 且 consumed 的 L3 Deployment Approval。"""

    return ApprovalRequest(
        task_id=task_id,
        action="approve_deployment",
        risk_level="L3",
        reason="验证 M7-2D Deployment 数据门禁。",
        resource_type="deployment",
        resource_id=resource_id,
        request_hash=REQUEST_HASH,
        status="approved",
        requested_by_agent_run_id=requester_agent_run_id,
        decided_by="reviewer",
        decided_at=now,
        expires_at=now + timedelta(minutes=30),
        consumed_at=now,
        created_at=now,
    )


def _artifact(
    *,
    task_id: UUID,
    artifact_type: str,
    suffix: str,
) -> Artifact:
    """构造不依赖文件写入的 system Artifact 元数据。"""

    return Artifact(
        task_id=task_id,
        producer_type="system",
        artifact_type=artifact_type,
        status="available",
        display_name=f"{artifact_type}.json",
        media_type="application/json",
        storage_key=f"m7-2d/{suffix}/{artifact_type}.json",
        sha256="sha256:" + suffix[:64].ljust(64, "0"),
        size_bytes=2,
        summary=f"M7-2D {artifact_type} fixture",
        metadata_json={},
        idempotency_key=f"m7-2d:{artifact_type}:{suffix}",
    )
