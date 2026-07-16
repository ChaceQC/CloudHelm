"""Celery task 入口；无通用 autoretry。"""

from __future__ import annotations

import os
import socket
from uuid import uuid4

from pydantic import ValidationError

from cloudhelm_platform_api.schemas.workflow_job import (
    WorkflowJobBrokerMessage,
)
from cloudhelm_workflow_engine.celery_app import celery_app
from cloudhelm_workflow_engine.worker_factory import get_worker_service

_PROCESS_BOOT_ID = uuid4()


@celery_app.task(
    name="cloudhelm.workflow.execute",
    bind=True,
    acks_late=True,
    reject_on_worker_lost=True,
    ignore_result=True,
)
def execute_workflow_job(self, **message: object) -> None:
    """解析严格 broker message 并推进 PostgreSQL 权威 job。"""

    try:
        payload = WorkflowJobBrokerMessage.model_validate(message)
    except ValidationError:
        # 非法 broker message 不含可可信的 job identity，正常 ack 丢弃。
        return
    delivery_id = self.request.id or str(uuid4())
    claim_token = uuid4()
    owner = (
        f"worker:{socket.gethostname()}:{os.getpid()}:"
        f"{_PROCESS_BOOT_ID}:{delivery_id}:{claim_token}"
    )
    get_worker_service().execute(
        workflow_job_id=payload.workflow_job_id,
        worker_owner=owner,
    )
