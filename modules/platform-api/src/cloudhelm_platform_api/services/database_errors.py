"""数据库约束错误的稳定识别与脱敏映射。"""

from sqlalchemy.exc import IntegrityError

from cloudhelm_platform_api.services.exceptions import ServiceError


def integrity_constraint_name(error: IntegrityError) -> str | None:
    """读取 PostgreSQL 驱动提供的约束名，不解析易漂移的错误文本。"""

    original = getattr(error, "orig", None)
    diagnostic = getattr(original, "diag", None)
    value = getattr(diagnostic, "constraint_name", None)
    return value if isinstance(value, str) else None


def database_write_error(error: IntegrityError) -> ServiceError:
    """把非预期约束异常转换为不泄露 SQL、参数和表结构的 500。"""

    return ServiceError(
        code="database_error",
        message="数据库写入失败。",
        status_code=500,
        detail=None,
    )
