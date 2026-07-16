"""Celery JSON/late-ack/visibility 固定配置。"""

from celery import Celery
from kombu import Queue

from cloudhelm_workflow_engine.config import (
    WorkflowSettings,
    get_workflow_settings,
)


def create_celery_app(
    settings: WorkflowSettings | None = None,
) -> Celery:
    """创建只承载 workflow job ID 的 Celery 应用。"""

    config = settings or get_workflow_settings()
    app = Celery(
        "cloudhelm-workflow-engine",
        broker=config.broker_url.get_secret_value(),
        backend=None,
        include=["cloudhelm_workflow_engine.tasks"],
    )
    app.conf.update(
        result_backend=None,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        enable_utc=True,
        timezone="UTC",
        task_protocol=2,
        task_acks_late=True,
        task_acks_on_failure_or_timeout=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_ignore_result=True,
        task_store_errors_even_if_ignored=False,
        task_track_started=False,
        task_soft_time_limit=config.soft_time_limit_seconds,
        task_time_limit=config.hard_time_limit_seconds,
        task_publish_retry=False,
        broker_connection_retry_on_startup=True,
        task_create_missing_queues=False,
        task_default_queue=config.queue_name,
        task_queues=(
            Queue(config.queue_name),
            Queue(config.maintenance_queue_name),
        ),
        task_routes={
            "cloudhelm.workflow.execute": {
                "queue": config.queue_name,
            }
        },
        broker_transport_options={
            "visibility_timeout": config.visibility_timeout_seconds,
            "socket_connect_timeout": (
                config.broker_publish_timeout_seconds
            ),
            "socket_timeout": config.broker_publish_timeout_seconds,
            "retry_on_timeout": False,
        },
    )
    return app


celery_app = create_celery_app()
