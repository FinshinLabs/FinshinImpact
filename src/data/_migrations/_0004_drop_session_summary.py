"""抹掉会话表的摘要列

- 先判列在不在再删
"""

import aiosqlite


async def apply(conn: aiosqlite.Connection) -> None:
    """删除会话表的摘要列"""
    if await _has_column(conn, "session", "summary"):
        await conn.execute("ALTER TABLE session DROP COLUMN summary")


async def _has_column(conn: aiosqlite.Connection, table: str, column: str) -> bool:
    """判断表里有没有这一列"""
    async with conn.execute(f"PRAGMA table_info({table})") as cursor:
        rows = await cursor.fetchall()
    return any(row["name"] == column for row in rows)
