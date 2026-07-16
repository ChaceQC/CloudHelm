"""M7 ServiceInstance 数据访问。"""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from cloudhelm_platform_api.models.service_instance import ServiceInstance
from cloudhelm_platform_api.repositories.pagination import fetch_page


class ServiceInstanceRepository:
    """ServiceInstance 表访问对象；只提供精确查询、批量写入和锁。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, instance: ServiceInstance) -> ServiceInstance:
        """新增单个 ServiceInstance。"""

        self.session.add(instance)
        self.session.flush()
        return instance

    def create_many(
        self,
        instances: Iterable[ServiceInstance],
    ) -> list[ServiceInstance]:
        """原子加入一批实例，并由调用方事务决定提交或回滚。"""

        values = list(instances)
        self.session.add_all(values)
        self.session.flush()
        return values

    def get(
        self,
        instance_id: UUID,
        *,
        for_update: bool = False,
    ) -> ServiceInstance | None:
        """按 ID 读取实例，可选加行锁。"""

        return self._one(
            select(ServiceInstance).where(
                ServiceInstance.id == instance_id
            ),
            for_update=for_update,
        )

    def get_by_deployment_service(
        self,
        deployment_id: UUID,
        service_name: str,
        *,
        for_update: bool = False,
    ) -> ServiceInstance | None:
        """按 Deployment 与 service name 读取唯一实例。"""

        return self._one(
            select(ServiceInstance).where(
                ServiceInstance.deployment_id == deployment_id,
                ServiceInstance.service_name == service_name,
            ),
            for_update=for_update,
        )

    def list_by_deployment(
        self,
        deployment_id: UUID,
    ) -> list[ServiceInstance]:
        """按 service name、UUID 稳定展示 Deployment 下全部实例。"""

        return list(
            self.session.scalars(
                select(ServiceInstance)
                .where(ServiceInstance.deployment_id == deployment_id)
                .order_by(
                    ServiceInstance.service_name,
                    ServiceInstance.id,
                )
            )
        )

    def list_by_deployment_for_update(
        self,
        deployment_id: UUID,
    ) -> list[ServiceInstance]:
        """按 UUID 固定顺序锁定 Deployment 下全部实例，避免死锁。"""

        return list(
            self.session.scalars(
                select(ServiceInstance)
                .where(ServiceInstance.deployment_id == deployment_id)
                .order_by(ServiceInstance.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def list_by_environment(
        self,
        environment_id: UUID,
        limit: int,
        cursor: str | None,
        *,
        status: str | None = None,
    ) -> tuple[list[ServiceInstance], str | None]:
        """按 Environment 稳定分页读取实例。"""

        statement: Select[tuple[ServiceInstance]] = (
            select(ServiceInstance)
            .where(ServiceInstance.environment_id == environment_id)
            .order_by(
                ServiceInstance.created_at.desc(),
                ServiceInstance.id.desc(),
            )
        )
        if status is not None:
            statement = statement.where(ServiceInstance.status == status)
        return fetch_page(self.session, statement, limit, cursor)

    def _one(
        self,
        statement: Select[tuple[ServiceInstance]],
        *,
        for_update: bool,
    ) -> ServiceInstance | None:
        """执行唯一结果查询，并统一行锁刷新语义。"""

        if for_update:
            statement = statement.with_for_update().execution_options(
                populate_existing=True
            )
        return self.session.scalar(statement.limit(1))
