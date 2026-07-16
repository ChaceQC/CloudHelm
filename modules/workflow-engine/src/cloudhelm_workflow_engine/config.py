"""Workflow Engine 环境配置与时间不变量。"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_QUEUE_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,127}$"


class WorkflowSettings(BaseSettings):
    """M7 dispatcher、worker、heartbeat 与 reclaimer 配置。"""

    model_config = SettingsConfigDict(
        env_prefix="CLOUDHELM_WORKFLOW_",
        extra="ignore",
    )

    database_url: SecretStr = Field(
        default=SecretStr(
            "postgresql+psycopg://cloudhelm:cloudhelm_dev@127.0.0.1:15432/cloudhelm"
        ),
        validation_alias="CLOUDHELM_DATABASE_URL",
        repr=False,
    )
    broker_url: SecretStr = Field(
        default=SecretStr("redis://127.0.0.1:16379/0"),
        validation_alias="CLOUDHELM_WORKFLOW_BROKER_URL",
        repr=False,
    )
    queue_name: str = Field(
        default="cloudhelm.workflow",
        pattern=_QUEUE_PATTERN,
    )
    maintenance_queue_name: str = Field(
        default="cloudhelm.workflow.maintenance",
        pattern=_QUEUE_PATTERN,
    )
    job_lease_seconds: int = Field(default=90, ge=3, le=86400)
    job_heartbeat_seconds: int = Field(default=20, ge=1, le=3600)
    dispatch_interval_seconds: int = Field(default=5, ge=1, le=3600)
    dispatch_lease_seconds: int = Field(default=15, ge=3, le=3600)
    broker_publish_timeout_seconds: int = Field(default=5, ge=1, le=300)
    redispatch_after_seconds: int = Field(default=60, ge=1, le=86400)
    enqueue_backoff_seconds: int = Field(default=1, ge=1, le=3600)
    max_enqueue_backoff_seconds: int = Field(default=60, ge=1, le=86400)
    retry_backoff_seconds: int = Field(default=5, ge=1, le=3600)
    max_retry_backoff_seconds: int = Field(default=300, ge=1, le=86400)
    reclaim_interval_seconds: int = Field(default=30, ge=1, le=3600)
    batch_size: int = Field(default=50, ge=1, le=1000)
    soft_time_limit_seconds: int = Field(default=840, ge=1, le=86400)
    hard_time_limit_seconds: int = Field(default=900, ge=2, le=86400)
    visibility_timeout_seconds: int = Field(default=1800, ge=3, le=172800)

    @model_validator(mode="after")
    def validate_time_invariants(self) -> "WorkflowSettings":
        """启动前拒绝会产生 lease/ack 空窗的组合。"""

        checks = (
            (
                2 * self.job_heartbeat_seconds < self.job_lease_seconds,
                "必须满足 2 * heartbeat < worker lease。",
            ),
            (
                self.reclaim_interval_seconds < self.job_lease_seconds,
                "reclaim interval 必须小于 worker lease。",
            ),
            (
                2 * self.broker_publish_timeout_seconds
                < self.dispatch_lease_seconds,
                "必须满足 2 * publish timeout < dispatch lease。",
            ),
            (
                self.dispatch_interval_seconds < self.dispatch_lease_seconds,
                "dispatch interval 必须小于 dispatch lease。",
            ),
            (
                self.redispatch_after_seconds > self.dispatch_lease_seconds,
                "redispatch 时间必须大于 dispatch lease。",
            ),
            (
                self.enqueue_backoff_seconds
                <= self.max_enqueue_backoff_seconds,
                "enqueue 初始退避不能大于最大退避。",
            ),
            (
                self.retry_backoff_seconds
                <= self.max_retry_backoff_seconds,
                "retry 初始退避不能大于最大退避。",
            ),
            (
                self.soft_time_limit_seconds
                < self.hard_time_limit_seconds
                < self.visibility_timeout_seconds,
                "必须满足 soft < hard < visibility timeout。",
            ),
            (
                self.visibility_timeout_seconds
                >= self.hard_time_limit_seconds + self.job_lease_seconds,
                "visibility 必须覆盖 hard timeout 与 worker lease。",
            ),
            (
                self.queue_name != self.maintenance_queue_name,
                "业务队列与 maintenance 队列必须不同。",
            ),
        )
        for valid, message in checks:
            if not valid:
                raise ValueError(message)
        return self


@lru_cache(maxsize=1)
def get_workflow_settings() -> WorkflowSettings:
    """返回当前进程不可变配置。"""

    return WorkflowSettings()
