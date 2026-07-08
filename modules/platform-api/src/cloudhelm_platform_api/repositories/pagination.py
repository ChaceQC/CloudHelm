"""Repository 分页辅助函数。"""

from typing import TypeVar

from sqlalchemy import Select
from sqlalchemy.orm import Session

T = TypeVar("T")


def parse_offset_cursor(cursor: str | None) -> int:
    """解析 M2 offset cursor。

    参数:
        cursor: API 查询参数，必须为空或非负整数。

    返回:
        可用于 SQL OFFSET 的整数。
    """

    if cursor is None:
        return 0
    try:
        offset = int(cursor)
    except ValueError:
        return 0
    return max(offset, 0)


def fetch_page(session: Session, statement: Select[tuple[T]], limit: int, cursor: str | None) -> tuple[list[T], str | None]:
    """执行 offset cursor 分页查询。

    M2 数据量较小，用 offset cursor 满足控制台开发；后续数据增长后可替换
    为 keyset pagination，API 响应结构无需改变。
    """

    offset = parse_offset_cursor(cursor)
    rows = list(session.scalars(statement.offset(offset).limit(limit + 1)))
    has_next = len(rows) > limit
    items = rows[:limit]
    next_cursor = str(offset + limit) if has_next else None
    return items, next_cursor
