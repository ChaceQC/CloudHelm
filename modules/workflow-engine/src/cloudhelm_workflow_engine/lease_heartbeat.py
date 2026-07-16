"""运行中 handler 的独立短 Session lease heartbeat。"""

from __future__ import annotations

import threading
from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from cloudhelm_platform_api.repositories.workflow_job_repository import (
    WorkflowJobRepository,
)


class LeaseHeartbeat:
    """后台续租；失败后由 terminal owner check 与 stale reclaim 裁决。"""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        workflow_job_id: UUID,
        worker_owner: str,
        lease_seconds: int,
        interval_seconds: int,
    ) -> None:
        self.session_factory = session_factory
        self.workflow_job_id = workflow_job_id
        self.worker_owner = worker_owner
        self.lease_seconds = lease_seconds
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._lease_lost = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def lease_lost(self) -> bool:
        """是否已观察到 owner/lease 无效或 heartbeat 异常。"""

        return self._lease_lost.is_set()

    def start(self) -> None:
        """启动单一 daemon heartbeat thread。"""

        if self._thread is not None:
            raise RuntimeError("LeaseHeartbeat 已启动。")
        self._thread = threading.Thread(
            target=self._run,
            name=f"workflow-heartbeat-{self.workflow_job_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """停止并等待线程退出。"""

        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval_seconds + 1)

    def tick_once(self) -> bool:
        """执行一次续租，供线程与白盒测试复用。"""

        try:
            with self.session_factory() as session:
                job = WorkflowJobRepository(session).heartbeat(
                    job_id=self.workflow_job_id,
                    worker_owner=self.worker_owner,
                    worker_lease=timedelta(seconds=self.lease_seconds),
                )
                session.commit()
        except Exception:
            self._lease_lost.set()
            return False
        if job is None:
            self._lease_lost.set()
            return False
        return True

    def _run(self) -> None:
        """按 interval 续租，stop 不等待完整周期。"""

        while not self._stop.wait(self.interval_seconds):
            if not self.tick_once():
                return
