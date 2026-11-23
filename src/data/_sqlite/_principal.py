"""主体仓储实装

- 按主体键读写 principal 表
"""

import time

import aiosqlite

from core import PrincipalRepository
from finshin_sdk.domain import PlatformCode
from finshin_sdk.domain.ids import ContainerCode, UserId
from finshin_sdk.dto import PrincipalDTO

_SELECT_COLUMNS = "platform, container, user"


class SqlitePrincipalRepository(PrincipalRepository):
    """主体仓储的 SQLite 实装"""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def upsert(self, principal: PrincipalDTO, display_name: str) -> PrincipalDTO:
        """写入或更新主体

        - 已存在时只刷显示名
        """
        await self._conn.execute(
            """
            INSERT INTO principal(key, platform, container, user,
                                  display_name, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                display_name = excluded.display_name
            """,
            (
                principal.dotted,
                principal.platform,
                principal.container,
                principal.user,
                display_name,
                time.time(),
            ),
        )
        await self._conn.commit()
        return principal


def _to_dto(row: aiosqlite.Row) -> PrincipalDTO:
    """行转主体快照"""
    return PrincipalDTO(
        platform=PlatformCode(row["platform"]),
        container=ContainerCode(row["container"]),
        user=UserId(row["user"]),
    )
