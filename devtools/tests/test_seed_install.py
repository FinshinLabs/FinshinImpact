"""接口件补装判定的单元测试

- 本机已装高于待装那版即不进装单，同版本照装，接口件不压新版
- 接口包在免装指纹里记发行件名、版本与指纹
- 装成功即从包根删掉接口件目录，目录不在场也不报错
"""

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "packaging"))

from launch import runtime as mod  # noqa: E402

_WHEEL = "finshin_sdk-0.1.0-py3-none-any.whl"


class TestAlreadyEnough(unittest.TestCase):
    """随包那只件还要不要再交给 uv"""

    def setUp(self) -> None:
        self.wheel = Path(_WHEEL)

    def test_newer_installed_is_enough(self) -> None:
        """本机更高即不装，随包件不压新版"""
        self.assertTrue(mod._already_enough(self.wheel, {"finshin-sdk": "0.2.0"}))

    def test_same_version_needs_install(self) -> None:
        """同版本照装：重打的件不靠版本号分辨"""
        self.assertFalse(mod._already_enough(self.wheel, {"finshin-sdk": "0.1.0"}))

    def test_lower_installed_needs_install(self) -> None:
        """本机更低即照装"""
        self.assertFalse(mod._already_enough(self.wheel, {"finshin-sdk": "0.0.9"}))

    def test_absent_needs_install(self) -> None:
        """本机没这只件即照装"""
        self.assertFalse(mod._already_enough(self.wheel, {}))

    def test_unreadable_installed_needs_install(self) -> None:
        """本机版本串读不懂即照装，不拿猜的当成够"""
        self.assertFalse(mod._already_enough(self.wheel, {"finshin-sdk": "最新"}))


class TestInstallPlan(unittest.TestCase):
    """装单"""

    def _root(self, stage: Path, installed: str = "") -> Path:
        """造一棵带接口件的包根，需要时补一个已装标记"""
        seed = stage / mod.PackLayout.SDK_WHEEL_DIR
        seed.mkdir(parents=True)
        (seed / _WHEEL).write_bytes(b"one")
        if installed:
            site = stage / mod.PackLayout.RUNTIME_DIR / "Lib" / "site-packages"
            site.mkdir(parents=True)
            (site / f"finshin_sdk-{installed}.dist-info").mkdir()
        return stage

    def test_newer_installed_keeps_the_wheel_out(self) -> None:
        """本机已装更高版本，装单里不留接口件"""
        with TemporaryDirectory() as raw:
            root = self._root(Path(raw), installed="0.2.0")
            with patch.object(mod, "dependencies", lambda _root: []):
                deps = mod._install_plan(root)
            self.assertEqual([item for item in deps if item.endswith(".whl")], [])

    def test_same_version_installed_puts_the_wheel_in(self) -> None:
        """本机同版本，装单里照样带接口件"""
        with TemporaryDirectory() as raw:
            root = self._root(Path(raw), installed="0.1.0")
            with patch.object(mod, "dependencies", lambda _root: []):
                deps = mod._install_plan(root)
            self.assertTrue([item for item in deps if item.endswith(".whl")])

    def test_absent_installed_puts_the_wheel_in(self) -> None:
        """本机没装，装单里按路径带上接口件"""
        with TemporaryDirectory() as raw:
            root = self._root(Path(raw))
            with patch.object(mod, "dependencies", lambda _root: []):
                deps = mod._install_plan(root)
            self.assertTrue([item for item in deps if item.endswith(".whl")])

    def test_no_seed_means_core_only(self) -> None:
        """接口件已被删掉，装单里只剩核心依赖"""
        with TemporaryDirectory() as raw:
            root = Path(raw) / "pack"
            root.mkdir()
            with patch.object(mod, "dependencies", lambda _root: ["pillow==12.1.1"]):
                deps = mod._install_plan(root)
            self.assertEqual(deps, ["pillow==12.1.1"])


class TestSdkStamp(unittest.TestCase):
    """接口包在免装指纹里的那一行"""

    def test_line_carries_name_version_and_digest(self) -> None:
        """发行件名、版本与指纹都在同一行"""
        self.assertEqual(mod._sdk_line("0.2.0", "abc"), "finshin-sdk==0.2.0#abc")

    def test_digest_read_back(self) -> None:
        """同版本那一行的指纹读得回来"""
        lines = ["pillow==12.1.1", "finshin-sdk==0.2.0#abc"]
        self.assertEqual(mod._installed_sdk_digest(lines, "0.2.0"), "abc")

    def test_other_version_not_adopted(self) -> None:
        """别的版本那一行不算已装"""
        lines = ["finshin-sdk==0.1.0#abc"]
        self.assertEqual(mod._installed_sdk_digest(lines, "0.2.0"), "")

    def test_missing_line_is_empty(self) -> None:
        """没有接口包那一行即交出空串"""
        self.assertEqual(mod._installed_sdk_digest([], "0.2.0"), "")


class TestDropSeeds(unittest.TestCase):
    """装成功后从包根删掉随包目录"""

    def test_seed_dir_is_gone(self) -> None:
        """随包目录整份删掉"""
        with TemporaryDirectory() as raw:
            root = self._root_with_seed(Path(raw))
            mod._drop_seeds(root)
            self.assertFalse((root / mod.PackLayout.SDK_WHEEL_DIR).exists())

    def test_missing_seed_dir_is_quiet(self) -> None:
        """目录不在场即什么都不做，不报错"""
        with TemporaryDirectory() as raw:
            mod._drop_seeds(Path(raw))

    def _root_with_seed(self, stage: Path) -> Path:
        """造一个带随包件的包根"""
        seed = stage / mod.PackLayout.SDK_WHEEL_DIR
        seed.mkdir(parents=True)
        (seed / _WHEEL).write_bytes(b"one")
        return stage


if __name__ == "__main__":
    unittest.main()
