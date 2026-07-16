"""M6 PullRequestRecord Task-first 并发串行化回归。"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_engine
from cloudhelm_platform_api.models.pull_request_record import PullRequestRecord
from cloudhelm_platform_api.schemas.pull_request_record import (
    PullRequestRecordCreate,
)
from cloudhelm_platform_api.services.pull_request_record_service import (
    PullRequestRecordService,
)
from m6_evidence_fixture import seed_m6_evidence


def test_concurrent_pr_creation_leaves_exactly_one_open_record() -> None:
    """不同 commit 并发创建时按 Task 行锁依次 supersede 前一条 open PR。"""

    evidence = seed_m6_evidence(
        "pr-task-lock",
        pull_request_count=1,
    )
    with Session(get_engine()) as session:
        seed_record = session.get(
            PullRequestRecord,
            evidence.pull_request_record_ids[0],
        )
        assert seed_record is not None
        common = {
            "task_id": seed_record.task_id,
            "project_id": seed_record.project_id,
            "development_plan_id": seed_record.development_plan_id,
            "created_by_agent_run_id": (
                seed_record.created_by_agent_run_id
            ),
            "title": seed_record.title,
            "summary": seed_record.summary,
            "base_branch": seed_record.base_branch,
            "base_commit_sha": seed_record.commit_sha,
            "changed_files_json": seed_record.changed_files_json,
            "diff_stat_json": seed_record.diff_stat_json,
            "diff_artifact_id": seed_record.diff_artifact_id,
            "test_artifact_id": seed_record.test_artifact_id,
            "review_artifact_id": seed_record.review_artifact_id,
            "security_artifact_id": seed_record.security_artifact_id,
        }
    barrier = Barrier(2)

    def create_record(index: int) -> UUID:
        with Session(get_engine(), expire_on_commit=False) as session:
            barrier.wait(timeout=10)
            record = PullRequestRecordService(session).create(
                PullRequestRecordCreate(
                    **common,
                    head_branch=f"codex/pr-task-lock-{index}",
                    commit_sha=f"{3000 + index:040x}",
                    idempotency_key=f"pr-task-lock:{index}",
                )
            )
            session.commit()
            return record.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        created_ids = list(pool.map(create_record, (1, 2)))

    assert len(set(created_ids)) == 2
    with Session(get_engine()) as session:
        records = list(
            session.scalars(
                select(PullRequestRecord)
                .where(
                    PullRequestRecord.task_id == evidence.task_id
                )
                .order_by(
                    PullRequestRecord.created_at,
                    PullRequestRecord.id,
                )
            )
        )
        assert len(records) == 3
        assert [record.status for record in records].count("open") == 1
        assert (
            [record.status for record in records].count("superseded")
            == 2
        )
