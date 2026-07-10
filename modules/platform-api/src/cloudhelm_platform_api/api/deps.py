"""FastAPI 依赖。"""

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from cloudhelm_platform_api.db.session import get_db_session


DbSession = Annotated[Session, Depends(get_db_session)]


def pagination_params(
    limit: Annotated[int, Query(ge=1, le=100, description="分页大小。")] = 50,
    cursor: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=18,
            pattern=r"^\d+$",
            description="非负十进制 offset cursor。",
        ),
    ] = None,
) -> tuple[int, str | None]:
    """统一校验分页参数，非法 cursor 由 FastAPI 返回 422。"""

    return limit, cursor
