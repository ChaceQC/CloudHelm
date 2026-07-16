"""Workflow Engine 稳定错误分类。"""

from __future__ import annotations

import socket

from kombu.exceptions import OperationalError as KombuOperationalError
from sqlalchemy.exc import DBAPIError, OperationalError


def broker_error_code(exc: BaseException) -> str:
    """把 broker 异常映射为不回显 URL/credential 的稳定错误码。"""

    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "workflow_broker_publish_timeout"
    if isinstance(exc, (ConnectionError, KombuOperationalError)):
        return "workflow_broker_unavailable"
    return "workflow_broker_publish_failed"


def is_transient_database_error(exc: BaseException) -> bool:
    """只把序列化、死锁和连接类 SQLSTATE 视为安全瞬时失败。"""

    if isinstance(exc, OperationalError):
        return True
    if not isinstance(exc, DBAPIError):
        return False
    sqlstate = getattr(exc.orig, "sqlstate", None)
    return bool(
        sqlstate in {"40001", "40P01"}
        or (isinstance(sqlstate, str) and sqlstate.startswith("08"))
    )
