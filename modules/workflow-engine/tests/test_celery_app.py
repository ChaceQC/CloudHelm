"""Celery 配置门禁。"""

from cloudhelm_workflow_engine.celery_app import create_celery_app
from cloudhelm_workflow_engine.config import WorkflowSettings


def test_celery_uses_json_late_ack_and_single_prefetch() -> None:
    """Celery 不保存结果，也不配置盲目 publish/autoretry。"""

    settings = WorkflowSettings()
    app = create_celery_app(settings)

    assert app.conf.task_serializer == "json"
    assert app.conf.accept_content == ["json"]
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_ignore_result is True
    assert app.conf.task_publish_retry is False
    assert app.conf.result_backend is None
    assert (
        app.conf.broker_transport_options["visibility_timeout"]
        == settings.visibility_timeout_seconds
    )
    assert app.conf.task_routes["cloudhelm.workflow.execute"]["queue"] == (
        settings.queue_name
    )
