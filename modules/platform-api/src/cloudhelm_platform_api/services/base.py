"""Service 通用能力。"""

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from cloudhelm_platform_api.services.exceptions import ServiceError


class BaseService:
    """为业务服务提供统一事务提交和回滚处理。"""

    def __init__(self, session: Session) -> None:
        self.session = session

    def commit(self) -> None:
        """提交当前事务。

        任何数据库异常都会回滚并转换为稳定业务错误，避免把驱动异常细节
        暴露给 API 调用方。
        """

        try:
            self.session.commit()
        except SQLAlchemyError as exc:
            self.session.rollback()
            raise ServiceError(
                code="database_error",
                message="数据库写入失败。",
                status_code=500,
                detail=str(exc),
            ) from exc
