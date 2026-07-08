"""FastAPI 依赖。"""

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_db_session


DbSession = Annotated[Session, Depends(get_db_session)]


def pagination_params(
    limit: Annotated[int, Query(ge=1, le=100, description="分页大小。")] = 50,
    cursor: Annotated[str | None, Query(description="offset cursor。")] = None,
) -> tuple[int, str | None]:
    """统一解析分页参数。"""

    return limit, cursor
