"""发布说明取数的单元测试

- 仓名只从 github.com 的 release 直链解析
- 翻页取到短页即停，草稿与预发布不进组件版本窗
- 当天缓存直接复用，隔天整份重取，坏文件按没有缓存处理
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from exceptions import RemoteVersionError  # noqa: E402
from services import release_feed as mod  # noqa: E402

_URL = (
    "https://github.com/FinshinLabs/finshin-adapter-tg/releases/download/"
    "v0.2.0/finshin_adapter_tg-0.2.0-py3-none-any.whl"
)


def _row(tag: str) -> dict[str, object]:
    """一条 release 接口条目"""
    return {"tag_name": tag, "body": f"{tag} 正文"}


class TestRepoOf(unittest.TestCase):
    """发布直链里的仓名"""

    def test_download_url_is_parsed(self) -> None:
        """下载直链取出属主与仓名"""
        repo = mod._repo_of(_URL)

        self.assertEqual(repo.owner, "FinshinLabs")
        self.assertEqual(repo.name, "finshin-adapter-tg")

    def test_releases_page_is_parsed(self) -> None:
        """release 页面地址同样认"""
        self.assertEqual(
            mod._repo_of("https://github.com/a/b/releases"),
            mod._Repo("a", "b"),
        )

    def test_bad_release_urls_rejected(self) -> None:
        """别的站点与同仓非 release 路径都读不出仓名"""
        for url in (
            "https://example.invalid/a/b/releases/download/v1/x.whl",
            "https://github.com/a/b/archive/v1.zip",
        ):
            with self.subTest(url=url):
                with self.assertRaises(RemoteVersionError):
                    mod._repo_of(url)


class TestPagination(unittest.IsolatedAsyncioTestCase):
    """按页取 release 列表"""

    async def test_short_page_stops(self) -> None:
        """取满一页接着取，短页即到底"""
        fetcher = AsyncMock(
            side_effect=[[_row("v0.3.0"), _row("v0.2.0")], [_row("v0.1.0")]]
        )
        with (
            patch.object(mod, "_RELEASE_PAGE_SIZE", 2),
            patch.object(mod.GitClient, "get_api", fetcher),
        ):
            notes = await mod._repo_notes(mod._Repo("a", "b"), formal_only=False)

        self.assertEqual([note.tag for note in notes], ["v0.3.0", "v0.2.0", "v0.1.0"])
        self.assertEqual(fetcher.await_count, 2)
        self.assertTrue(str(fetcher.call_args_list[0].args[0]).endswith("page=1"))
        self.assertTrue(str(fetcher.call_args_list[1].args[0]).endswith("page=2"))

    async def test_prerelease_is_filtered(self) -> None:
        """组件版本窗只收正式 release"""
        rows = [
            {"tag_name": "v0.3.0", "body": "", "prerelease": False},
            {"tag_name": "v0.2.0", "body": "", "prerelease": True},
            {"tag_name": "v0.1.0", "body": "", "draft": True},
            _row("v0.1.0"),
        ]
        with patch.object(mod.GitClient, "get_api", AsyncMock(return_value=rows)):
            notes = await mod._repo_notes(mod._Repo("a", "b"), formal_only=True)

        self.assertEqual([note.tag for note in notes], ["v0.3.0", "v0.1.0"])


class TestNoteBody(unittest.TestCase):
    """正文清洗"""

    def test_body_cleaning(self) -> None:
        """发布包直链行不留在正文，其余裸链接补成尖括号"""
        cases = (
            ("正文\nhttps://github.com/a/b/releases/download/v0.1.0/x.whl", "正文"),
            ("见 https://example.com/a", "见 <https://example.com/a>"),
        )
        for body, want in cases:
            with self.subTest(want=want):
                note = mod._to_note({"tag_name": "v0.1.0", "body": body})

                self.assertEqual(note.body, want)


class TestCache(unittest.IsolatedAsyncioTestCase):
    """当天复用与跨天重取"""

    def setUp(self) -> None:
        """缓存落临时目录"""
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self._root = Path(holder.name)

    async def _component_notes(
        self, today: str, fetcher: AsyncMock
    ) -> tuple[mod.ReleaseNote, ...]:
        """按临时缓存目录跑一次取数"""
        with (
            patch.object(mod, "RUNTIME_DIR", self._root),
            patch.object(mod, "_repo_notes", fetcher),
        ):
            return await mod.component_notes(_URL, today=today)

    def _cache_file(self) -> Path:
        return self._root / "release-notes" / "FinshinLabs.finshin-adapter-tg.json"

    async def test_same_day_hits_cache(self) -> None:
        """同一天第二次直接读缓存，不再发请求"""
        fetcher = AsyncMock(return_value=(mod.ReleaseNote("v0.2.0", "正文"),))
        first = await self._component_notes("2026-11-23", fetcher)
        second = await self._component_notes("2026-11-23", fetcher)

        self.assertEqual(fetcher.await_count, 1)
        self.assertEqual(second, first)
        self.assertEqual(
            json.loads(self._cache_file().read_text(encoding="utf-8"))["date"],
            "2026-11-23",
        )

    async def test_next_day_refetches(self) -> None:
        """隔天整份重取"""
        fetcher = AsyncMock(return_value=(mod.ReleaseNote("v0.2.0", "正文"),))
        await self._component_notes("2026-11-23", fetcher)
        await self._component_notes("2026-11-24", fetcher)

        self.assertEqual(fetcher.await_count, 2)
        self.assertEqual(
            json.loads(self._cache_file().read_text(encoding="utf-8"))["date"],
            "2026-11-24",
        )

    async def test_broken_cache_refetches(self) -> None:
        """缓存文件读不出即按没有缓存处理"""
        self._cache_file().parent.mkdir(parents=True)
        self._cache_file().write_text("{不是 JSON", encoding="utf-8")
        fetcher = AsyncMock(return_value=(mod.ReleaseNote("v0.2.0", "正文"),))

        notes = await self._component_notes("2026-11-23", fetcher)

        self.assertEqual([note.tag for note in notes], ["v0.2.0"])
        self.assertEqual(fetcher.await_count, 1)


if __name__ == "__main__":
    unittest.main()
