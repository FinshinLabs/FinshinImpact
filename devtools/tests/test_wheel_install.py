"""wheel 装机的单元测试

- 一条命令带全部件与 --find-links，参数紧跟子命令名
- 整批失败转逐只重试并逐只点名，依赖无解即整批记失败不再重试
- 开发模式只交等效手动命令，不动环境
- 元数据里声明的接口包要求读得出，没声明或读不出即空串
"""

import sys
import tempfile
import unittest
import zipfile
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from services.env_setup import wheel_install as mod  # noqa: E402

_SDK_NAME = "finshin-sdk"
_TG_NAME = "finshin-adapter-tg"


def _file(distribution: str, stem: str) -> mod.WheelFile:
    """拼一只落在 wheel 目录里的件"""
    return mod.WheelFile(
        distribution=distribution,
        version="0.1.0",
        path=Path("wheels") / f"{stem}-0.1.0-py3-none-any.whl",
    )


def _reads_back(name: str) -> str:
    """装完本机读到的版本，按要装的版本满足"""
    return "0.1.0"


def _files() -> list[mod.WheelFile]:
    """接口包与适配器各一只件"""
    return [_file(_SDK_NAME, "finshin_sdk"), _file(_TG_NAME, "finshin_adapter_tg")]


class TestInstallReleases(unittest.TestCase):
    """uv 装机与差集收集"""

    def setUp(self) -> None:
        """准备两只件与参数记录仪"""
        self.calls: list[list[str]] = []

    def _retry(
        self, code: int, unresolved: bool = False
    ) -> Callable[..., tuple[int, bool]]:
        """按固定退出码记下每次参数的替身"""

        def fake(args: list[str], on_line: object = None) -> tuple[int, bool]:
            self.calls.append(list(args))
            return code, unresolved

        return fake

    def test_batch_success_needs_no_notes(self) -> None:
        """一条命令带两只件，全成即无说明"""
        with (
            patch.object(mod, "dev_mode", lambda: False),
            patch.object(mod, "with_index_retry", self._retry(0)),
            patch.object(mod, "installed_version", _reads_back),
        ):
            notes = mod.install_releases(_files(), None)

        self.assertEqual(notes, [])
        self.assertEqual(len(self.calls), 1)
        argv = self.calls[0]
        self.assertEqual(argv[:2], ["pip", "install"])
        self.assertEqual(argv[2], "--python")
        self.assertEqual(argv[4], "--cache-dir")
        self.assertIn("--find-links", argv)
        self.assertEqual(argv.count("--find-links"), 1)
        self.assertTrue(all(str(item.path) in argv for item in _files()))
        self.assertIn(f"--reinstall-package={_SDK_NAME}", argv)
        self.assertIn(f"--reinstall-package={_TG_NAME}", argv)

    def test_batch_failure_retries_each(self) -> None:
        """整批失败转逐只重试并逐只点名"""
        with (
            patch.object(mod, "dev_mode", lambda: False),
            patch.object(mod, "with_index_retry", self._retry(1)),
            patch.object(mod, "installed_version", _reads_back),
        ):
            notes = mod.install_releases(_files(), None)

        self.assertEqual(len(self.calls), 3)
        self.assertEqual(len(notes), 2)
        self.assertIn(_SDK_NAME, notes[0])
        self.assertIn(_TG_NAME, notes[1])
        self.assertIn("装不进运行环境", notes[0])

    def test_failed_item_is_not_read_back(self) -> None:
        """逐只也全失败的件只报装不进，不再读本机版本"""
        with (
            patch.object(mod, "dev_mode", lambda: False),
            patch.object(mod, "with_index_retry", self._retry(1)),
            patch.object(mod, "installed_version", lambda name: "0.0.9"),
        ):
            notes = mod.install_releases(_files(), None)

        self.assertEqual(len(notes), 2)
        self.assertTrue(all("装不进运行环境" in note for note in notes))
        self.assertFalse(any("装完读到" in note for note in notes))

    def test_only_installed_item_is_read_back(self) -> None:
        """整批失败后第一只补救成功，只复核这一只"""
        reads: list[str] = []

        def record_read(name: str) -> str:
            reads.append(name)
            return "0.1.0"

        codes = iter([1, 0, 1])

        def fake(args: list[str], on_line: object = None) -> tuple[int, bool]:
            self.calls.append(list(args))
            return next(codes), False

        with (
            patch.object(mod, "dev_mode", lambda: False),
            patch.object(mod, "with_index_retry", fake),
            patch.object(mod, "installed_version", record_read),
        ):
            notes = mod.install_releases(_files(), None)

        self.assertEqual(reads, [_SDK_NAME])
        self.assertEqual(len(notes), 1)
        self.assertIn(_TG_NAME, notes[0])

    def test_unresolved_batch_skips_per_item_retry(self) -> None:
        """依赖无解即整批记失败，只跑一条命令并逐只点名"""
        with (
            patch.object(mod, "dev_mode", lambda: False),
            patch.object(mod, "with_index_retry", self._retry(1, unresolved=True)),
            patch.object(mod, "installed_version", _reads_back),
        ):
            notes = mod.install_releases(_files(), None)

        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(notes), 2)
        self.assertIn(_SDK_NAME, notes[0])
        self.assertIn(_TG_NAME, notes[1])
        self.assertIn("装不进运行环境", notes[0])

    def test_dev_mode_only_prints_command(self) -> None:
        """开发模式只交等效手动命令，不跑子进程"""
        lines: list[str] = []

        def collect(text: str) -> None:
            lines.append(text)

        with (
            patch.object(mod, "dev_mode", lambda: True),
            patch.object(mod, "with_index_retry", self._retry(0)),
        ):
            notes = mod.install_releases(_files(), collect)

        self.assertEqual(self.calls, [])
        self.assertEqual(len(notes), 2)
        self.assertTrue(any("uv pip install" in line for line in lines))

    def test_stale_version_after_install_is_named(self) -> None:
        """命令退出 0 但本机仍读到旧版本，也要点名而不是报成功"""
        with (
            patch.object(mod, "dev_mode", lambda: False),
            patch.object(mod, "with_index_retry", self._retry(0)),
            patch.object(mod, "installed_version", lambda name: "0.0.9"),
        ):
            notes = mod.install_releases(_files(), None)

        self.assertEqual(len(notes), 2)
        self.assertIn("装完读到 0.0.9", notes[0])
        self.assertIn(_SDK_NAME, notes[0])
        self.assertIn(_TG_NAME, notes[1])

    def test_empty_files_do_nothing(self) -> None:
        """没有要装的件即不动"""
        with (
            patch.object(mod, "dev_mode", lambda: False),
            patch.object(mod, "with_index_retry", self._retry(0)),
        ):
            notes = mod.install_releases([], None)

        self.assertEqual(notes, [])
        self.assertEqual(self.calls, [])


class TestSdkRequires(unittest.TestCase):
    """从 wheel 元数据读接口包要求"""

    def _wheel(self, metadata: str | None) -> Path:
        """临时目录里造一只带指定元数据的 wheel"""
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        path = Path(holder.name) / "demo-0.1.0-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            if metadata is not None:
                archive.writestr("demo-0.1.0.dist-info/METADATA", metadata)

        return path

    def test_reads_declared_range(self) -> None:
        """声明了接口包要求即原样交出"""
        metadata = (
            "Metadata-Version: 2.1\n"
            "Name: demo\n"
            "Requires-Dist: finshin-sdk (>=0.1.0,<0.2.0)\n"
        )
        path = self._wheel(metadata)

        self.assertEqual(mod.sdk_requires(path), ">=0.1.0,<0.2.0")

    def test_no_declaration_is_empty(self) -> None:
        """没声明接口包即空串"""
        path = self._wheel("Metadata-Version: 2.1\nName: demo\n")

        self.assertEqual(mod.sdk_requires(path), "")

    def test_broken_wheel_is_empty(self) -> None:
        """元数据读不出即空串，不拦住装机"""
        path = self._wheel(None)

        self.assertEqual(mod.sdk_requires(path), "")


if __name__ == "__main__":
    unittest.main()
