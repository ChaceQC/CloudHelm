"""Celery broker publisher；数据库事务提交后才允许调用。"""

from __future__ import annotations

from collections.abc import Sequence

from celery import Celery
from kombu import Producer

from cloudhelm_platform_api.repositories.workflow_job_repository import (
    DispatchReservation,
)
from cloudhelm_platform_api.schemas.workflow_job import (
    WorkflowJobBrokerMessage,
)
from cloudhelm_workflow_engine.config import WorkflowSettings
from cloudhelm_workflow_engine.errors import broker_error_code
from cloudhelm_workflow_engine.schemas import PublishOutcome


class CeleryBrokerPublisher:
    """一次 batch 复用一个 broker connection，并禁用隐式 publish retry。"""

    def __init__(
        self,
        *,
        app: Celery,
        settings: WorkflowSettings,
    ) -> None:
        self.app = app
        self.settings = settings

    def publish_batch(
        self,
        reservations: Sequence[DispatchReservation],
    ) -> list[PublishOutcome]:
        """发布严格 job ID message；异常只返回稳定错误码。"""

        if not reservations:
            return []
        try:
            with self.app.connection_for_write() as connection:
                connection.ensure_connection(
                    max_retries=0,
                    timeout=(
                        self.settings.broker_publish_timeout_seconds
                    ),
                )
                with connection.channel() as channel:
                    producer = Producer(channel, serializer="json")
                    return [
                        self._publish_one(producer, reservation)
                        for reservation in reservations
                    ]
        except Exception as exc:
            error_code = broker_error_code(exc)
            return [
                PublishOutcome(
                    reservation=reservation,
                    error_code=error_code,
                )
                for reservation in reservations
            ]

    def _publish_one(
        self,
        producer: Producer,
        reservation: DispatchReservation,
    ) -> PublishOutcome:
        """使用已建立连接发布一条 message。"""

        message = WorkflowJobBrokerMessage(
            workflow_job_id=reservation.workflow_job_id
        )
        try:
            self.app.send_task(
                "cloudhelm.workflow.execute",
                kwargs=message.model_dump(mode="json"),
                queue=self.settings.queue_name,
                serializer="json",
                retry=False,
                producer=producer,
            )
        except Exception as exc:
            return PublishOutcome(
                reservation=reservation,
                error_code=broker_error_code(exc),
            )
        return PublishOutcome(
            reservation=reservation,
            error_code=None,
        )
