"""任务状态账测试

- 真库往返，一条串一行、状态只朝一个方向走
- 同主体多条入队只落一行，最后一条落定才写终态
- 落库前先把主体行写上，外键才有落点
- 收尾只抹内存计数，库里那行原样留着
- 库打不开时记账失败只上报，不往外抛
"""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from db_template import copy_migrated_db  # noqa: E402

from data import (  # noqa: E402
    build_repositories,
    close_all,
    get_connection,
)
from finshin_sdk import HandlerContext  # noqa: E402
from finshin_sdk.domain import ChatScope, TaskStatus  # noqa: E402
from finshin_sdk.domain.ids import (  # noqa: E402
    ContainerCode,
    MessageId,
    PlatformCode,
    SessionKey,
    TaskKey,
    UserId,
)
from finshin_sdk.dto import (  # noqa: E402
    ContentDTO,
    InboundEventDTO,
    MessageRefDTO,
    PrincipalDTO,
    TaskDTO,
)
from services.tasks import TaskItem, TaskLedger  # noqa: E402

_CONTAINER = ContainerCode("g100123")


def _item(user: str, message_id: str = "7") -> TaskItem:
    """构造一条排队项"""
    principal = PrincipalDTO(
        platform=PlatformCode("tg"), container=_CONTAINER, user=UserId(user)
    )
    event = InboundEventDTO(
        ref=MessageRefDTO(
            platform=PlatformCode("tg"),
            container=_CONTAINER,
            message_id=MessageId(message_id),
        ),
        principal=principal,
        content=ContentDTO(text="说一句"),
        scope=ChatScope.GROUP,
        display_name="张三",
    )
    return TaskItem(
        container_key=SessionKey(f"{principal.platform}.{_CONTAINER}"),
        principal_key=principal.dotted,
        kind="demo.chat",
        ctx=HandlerContext(event=event, interaction=SimpleNamespace()),  # type: ignore[arg-type]
    )


class TestTaskLedger(unittest.IsolatedAsyncioTestCase):
    """一条串一行的粗账"""

    async def asyncSetUp(self) -> None:
        self.faults: list[tuple[TaskItem, Exception]] = []
        tmp = tempfile.TemporaryDirectory(prefix="finshin-ledger-")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.db = root / "bot.db"
        await copy_migrated_db(self.db)
        conn = await get_connection(self.db)
        self.addAsyncCleanup(close_all)
        self.repos = build_repositories(conn)
        self.ledger = TaskLedger(self.db, on_fault=self._fault)

    def _fault(self, item: TaskItem, error: Exception) -> None:
        """记账失败收进本用例"""
        self.faults.append((item, error))

    async def _row(self, user: str) -> TaskDTO | None:
        """取出该主体的任务行"""
        key = f"tg.{_CONTAINER}.{user}"
        return await self.repos.task.find(TaskKey(f"{key}.demo.chat"))

    async def test_first_of_a_run_inserts_one_row(self) -> None:
        """头一条入队即落行，主体行一并写上"""
        await self.ledger.enqueue(_item("111"))

        row = await self._row("111")
        assert row is not None
        self.assertEqual(row.status, TaskStatus.PENDING)
        # 主体行没有对外读口，直接查库确认账本确实一并写上
        conn = await get_connection(self.db)
        async with conn.execute("SELECT COUNT(*) FROM principal") as cursor:
            self.assertEqual((await cursor.fetchone())[0], 1)
        self.assertEqual(self.faults, [])

    async def test_same_principal_shares_one_row(self) -> None:
        """同主体第二条只加计数，库里仍是一行"""
        await self.ledger.enqueue(_item("111", "7"))
        await self.ledger.enqueue(_item("111", "8"))
        await self.ledger.begin(_item("111", "7"))

        row = await self._row("111")
        assert row is not None
        self.assertEqual(row.status, TaskStatus.RUNNING)

    async def test_tail_of_a_run_writes_the_final_state(self) -> None:
        """整串最后一条落定才写终态，前面几条不动库"""
        first, second = _item("111", "7"), _item("111", "8")
        await self.ledger.enqueue(first)
        await self.ledger.enqueue(second)
        await self.ledger.begin(first)

        await self.ledger.settle(first, failed=False)
        assert (await self._row("111")) is not None
        self.assertEqual((await self._row("111")).status, TaskStatus.RUNNING)

        await self.ledger.begin(second)
        await self.ledger.settle(second, failed=False)

        self.assertEqual((await self._row("111")).status, TaskStatus.SUCCEEDED)
        self.assertEqual(self.faults, [])

    async def test_failed_tail_marks_failed(self) -> None:
        """最后一条报错即记失败"""
        only = _item("222")
        await self.ledger.enqueue(only)
        await self.ledger.begin(only)

        await self.ledger.settle(only, failed=True)

        self.assertEqual((await self._row("222")).status, TaskStatus.FAILED)

    async def test_settle_without_begin_marks_failed(self) -> None:
        """没开过答就落定即没答上，记失败而非成功"""
        only = _item("333")
        await self.ledger.enqueue(only)

        await self.ledger.settle(only, failed=False)

        self.assertEqual((await self._row("333")).status, TaskStatus.FAILED)
        self.assertEqual(self.faults, [])

    async def test_reset_keeps_the_row_open(self) -> None:
        """收尾抹掉内存计数，库里那行留在在跑等下次交代"""
        only = _item("111")
        await self.ledger.enqueue(only)
        await self.ledger.begin(only)

        self.ledger.reset()
        await self.ledger.enqueue(_item("444"))

        self.assertEqual((await self._row("111")).status, TaskStatus.RUNNING)
        self.assertEqual((await self._row("444")).status, TaskStatus.PENDING)

    async def test_unreachable_db_reports_only(self) -> None:
        """库打不开时记账失败只上报，入队不往外抛"""
        broken = TaskLedger(
            Path(tempfile.gettempdir()) / "没有这只目录" / "bot.db",
            on_fault=self._fault,
        )

        await broken.enqueue(_item("111"))
        await broken.begin(_item("111"))
        await broken.settle(_item("111"), failed=False)

        self.assertEqual(len(self.faults), 3)


if __name__ == "__main__":
    unittest.main()
