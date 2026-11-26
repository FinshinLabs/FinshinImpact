"""平台组件装卸动作的单元测试

- 卸一只适配器只动它自己与只有它声明过的库
- 卸之前先数这一平台还剩几个实例，认不出平台的目录不算
- 取回的件声明的接口包要求本机不满足即不装，只报那一句
"""

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from finshin_sdk.domain.ids import PlatformCode  # noqa: E402
from services.adapter_catalog import ReleaseRow  # noqa: E402
from services.adapter_manifest import InstalledAdapter  # noqa: E402
from services.env_setup import platform_apply as mod  # noqa: E402

_ADAPTER = "finshin-adapter-tg"
_SHA = "0" * 64


def _adapter(version: str) -> InstalledAdapter:
    """一只已装的 Telegram 适配器包"""
    return InstalledAdapter(
        platform=PlatformCode("tg"),
        distribution=_ADAPTER,
        version=version,
        requires=("aiogram==3.29.1", "finshin-sdk>=0.1.0"),
        entry="finshin_adapter_tg.entry",
    )


class TestUninstallNames(unittest.TestCase):
    """卸一只适配器要动的发行件名"""

    def test_only_its_own_libraries(self) -> None:
        """适配器包自身与只有它声明过的库进名单"""
        with (
            patch.object(mod, "installed_adapters", lambda: (_adapter("0.1.0"),)),
            patch.object(
                mod, "keep_union", lambda exclude=None: ["finshin-sdk==0.1.0", "pillow"]
            ),
        ):
            self.assertEqual(
                mod.uninstall_names(str(PlatformCode("tg"))),
                (_ADAPTER, "aiogram"),
            )

    def test_absent_adapter_names_nothing(self) -> None:
        """本机没装那只包即一个名字都不交"""
        with patch.object(mod, "installed_adapters", lambda: ()):
            self.assertEqual(mod.uninstall_names(str(PlatformCode("tg"))), ())


class TestInstancesOf(unittest.TestCase):
    """卸适配器前先查的实例数"""

    def test_counts_only_that_platform(self) -> None:
        """只数这一平台的实例，认不出平台的目录不算"""
        profiles = [("tg.1", ""), ("tg.2", ""), ("qq.3", ""), ("别的", "")]
        with patch.object(mod, "list_profiles", lambda: profiles):
            self.assertEqual(mod.instances_of("tg"), 2)
            self.assertEqual(mod.instances_of("qq"), 1)


class TestSdkGap(unittest.TestCase):
    """取回的件要的接口包本机不满足即不装"""

    def _wheel(self, requires: str) -> Path:
        """临时目录里造一只带接口包要求的 wheel"""
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        path = Path(holder.name) / "finshin_adapter_tg-0.1.0-py3-none-any.whl"
        metadata = "Metadata-Version: 2.1\nName: finshin-adapter-tg\n"
        if requires:
            metadata += f"Requires-Dist: finshin-sdk ({requires})\n"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("finshin_adapter_tg-0.1.0.dist-info/METADATA", metadata)

        return path

    def _release(self) -> ReleaseRow:
        return ReleaseRow(
            distribution=_ADAPTER,
            version="0.1.0",
            url="https://example.invalid/x.whl",
            sha256=_SHA,
        )

    def test_unmet_requirement_blocks(self) -> None:
        """本机接口包不在区间内或缺件都在件里写的区间上被拦住，各交对应那句"""
        cases = (
            (
                "0.2.0",
                ">=0.1.0,<0.2.0",
                f"{_ADAPTER} 0.1.0 要接口包 >=0.1.0,<0.2.0，本机是 0.2.0",
            ),
            ("", ">=0.1.0", f"{_ADAPTER} 0.1.0 要接口包 >=0.1.0，本机缺接口包"),
        )
        for installed, requires, want in cases:
            with self.subTest(installed=installed):
                with patch.object(
                    mod, "installed_version", lambda name, _v=installed: _v
                ):
                    note = mod._sdk_gap(self._release(), self._wheel(requires))

                self.assertEqual(note, want)

    def test_met_requirement_passes(self) -> None:
        """本机落在区间内或件里没写要求即放行"""
        for installed, requires in (("0.1.5", ">=0.1.0,<0.2.0"), ("0.2.0", "")):
            with self.subTest(requires=requires):
                with patch.object(
                    mod, "installed_version", lambda name, _v=installed: _v
                ):
                    self.assertEqual(
                        mod._sdk_gap(self._release(), self._wheel(requires)), ""
                    )


class TestApplyUpdates(unittest.IsolatedAsyncioTestCase):
    """取件之后先验接口包要求再交装机"""

    async def test_gapped_release_not_installed(self) -> None:
        """接口包不满足的那只不进装机那批，只交一句说明"""
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        path = Path(holder.name) / "finshin_adapter_tg-0.1.0-py3-none-any.whl"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "finshin_adapter_tg-0.1.0.dist-info/METADATA",
                "Metadata-Version: 2.1\nName: finshin-adapter-tg\n"
                "Requires-Dist: finshin-sdk (>=0.1.0,<0.2.0)\n",
            )
        release = ReleaseRow(
            distribution=_ADAPTER,
            version="0.1.0",
            url="https://example.invalid/x.whl",
            sha256=_SHA,
        )
        outcome = SimpleNamespace(path=path, distribution=_ADAPTER, note="")
        installed: list[object] = []

        async def fake_download(*args: object, **kwargs: object) -> object:
            return outcome

        def fake_install(files: object, on_line: object = None) -> list[str]:
            installed.append(files)
            return []

        with (
            patch.object(mod, "download_release", fake_download),
            patch.object(mod, "install_releases", fake_install),
            patch.object(mod, "installed_version", lambda name: "0.2.0"),
        ):
            notes = await mod.apply_updates([release], None)

        self.assertEqual(installed, [])
        self.assertEqual(len(notes), 1)
        self.assertEqual(
            notes[0],
            f"{_ADAPTER} 0.1.0 要接口包 >=0.1.0,<0.2.0，本机是 0.2.0",
        )


if __name__ == "__main__":
    unittest.main()
