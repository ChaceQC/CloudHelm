"""业务异常定义。"""

from typing import Any


class ServiceError(Exception):
    """可转换为统一 API 错误响应的业务异常。"""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        detail: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail
