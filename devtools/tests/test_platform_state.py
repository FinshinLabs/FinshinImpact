"""平台组件读数的单元测试

- 行的拼装、归属档与装挡判定同一条链路，两份模块一起过
- 版本串读不懂、在线不比本机新、源码仓挂着且已装包都算本机已有
- 该装的那批只收本机没有与在线更新的两档
- 接口包那行只报读数，固定归本机已有且没有该装的一版
- 接口包没到位或高出上限时适配器那颗不给装
- 适配器那颗按要装那一版声明的要求挡，那一版没写要求即回落已装声明
- 在场平台只看已装包，源码仓挂着没装的不算
- 版本窗逐版报本机状态，挡不挡按同一条判据现算
- 来源按源码仓在不在场与包装没装进环境分四档，来路按内容从哪儿取到分三档

- 夹具一律合成值，线上发新版不许把用例改红
- 接口包源码仓那份声明也不读盘，读盘会把开发机的挂载状态混进用例
"""

import hashlib
import sys
import tempfile
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from finshin_sdk.domain.ids import PlatformCode  # noqa: E402
from services.adapter_catalog import Catalog, ReleaseRow  # noqa: E402
from services.adapter_manifest import InstalledAdapter  # noqa: E402
from services.env_setup import platform_rows as rows_mod  # noqa: E402
from services.env_setup import platform_state as mod  # noqa: E402

_ADAPTER = "finshin-adapter-tg"
_SDK = "finshin-sdk"
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


def _catalog(version: str) -> Catalog:
    """只列 Telegram 一行目录的清单"""
    return Catalog(
        sdk=None,
        adapters={
            PlatformCode("tg"): ReleaseRow(
                distribution=_ADAPTER,
                version=version,
                url=f"https://example.invalid/{_ADAPTER}.whl",
                sha256=_SHA,
            )
        },
        rejects=(),
    )


def _tg_row(installed: str, online: str, tree: bool = False) -> rows_mod.ComponentRow:
    """按本机在场版本、在线版本与来路排出一行读数"""
    item = _adapter(installed) if installed else None
    tree_names = {PlatformCode("tg"): _ADAPTER} if tree else {}
    with (
        patch.object(
            rows_mod, "installed_adapters", lambda: () if item is None else (item,)
        ),
        patch.object(rows_mod, "tree_distributions", lambda: tree_names),
        patch.object(rows_mod, "load_adapter_manifests", lambda: {}),
        patch.object(rows_mod, "installed_version", lambda name: ""),
        patch.object(rows_mod, "project_value", lambda key, path: ""),
    ):
        rows = rows_mod.component_rows(_catalog(online))

    return next(row for row in rows if row.platform == str(PlatformCode("tg")))


def _rows(sdk: str, adapter: str) -> tuple[rows_mod.ComponentRow, ...]:
    """接口包与 Telegram 各一行读数，本机在场版本按点名给"""
    item = _adapter(adapter) if adapter else None
    with (
        patch.object(
            rows_mod, "installed_adapters", lambda: () if item is None else (item,)
        ),
        patch.object(rows_mod, "tree_distributions", lambda: {}),
        patch.object(rows_mod, "load_adapter_manifests", lambda: {}),
        patch.object(rows_mod, "installed_version", lambda name: sdk),
        patch.object(rows_mod, "project_value", lambda key, path: ""),
    ):
        return rows_mod.component_rows(_catalog("0.1.0"))


def _adapter_row(rows: tuple[rows_mod.ComponentRow, ...]) -> rows_mod.ComponentRow:
    """读数里 Telegram 那一行"""
    return next(row for row in rows if row.platform == str(PlatformCode("tg")))


_WHEEL_BODY = b"wheel body"


def _release_row(version: str, sha: str, distribution: str = _ADAPTER) -> ReleaseRow:
    """一行目录，直链末段按版本号拼出 wheel 文件名"""
    stem = distribution.replace("-", "_")

    return ReleaseRow(
        distribution=distribution,
        version=version,
        url=f"https://example.invalid/{stem}-{version}-py3-none-any.whl",
        sha256=sha,
    )


def _wheel_name(version: str, distribution: str = _ADAPTER) -> str:
    """wheel 文件名，与目录行直链末段同一写法"""
    stem = distribution.replace("-", "_")

    return f"{stem}-{version}-py3-none-any.whl"


def _wheel_on(root: Path, version: str, distribution: str = _ADAPTER) -> str:
    """在临时目录落一份 wheel 件，交出它的指纹"""
    (root / _wheel_name(version, distribution)).write_bytes(_WHEEL_BODY)

    return hashlib.sha256(_WHEEL_BODY).hexdigest()


def _multi_row(installed: str, *versions: ReleaseRow) -> rows_mod.ComponentRow:
    """一行读数，目录行内按给定次序带版本清单"""
    newest, *_older = versions
    release = replace(newest, versions=tuple(versions))

    return rows_mod.ComponentRow(
        platform=str(PlatformCode("tg")),
        distribution=_ADAPTER,
        source=rows_mod.ComponentSource.INSTALLED,
        installed=installed,
        requires="",
        release=release,
        bucket=rows_mod.ComponentBucket.UPGRADABLE,
    )


def _component(
    platform: str,
    distribution: str,
    installed: str,
    requires: str,
    *versions: str,
) -> rows_mod.ComponentRow:
    """一行读数，目录行内按给定次序带版本清单，本机有在场件即算可更新"""
    rows = [_release_row(version, _SHA, distribution) for version in versions]
    release = replace(rows[0], versions=tuple(rows)) if rows else None
    bucket = (
        rows_mod.ComponentBucket.LOCAL
        if not installed or release is None
        else rows_mod.ComponentBucket.UPGRADABLE
    )

    return rows_mod.ComponentRow(
        platform=platform,
        distribution=distribution,
        source=rows_mod.ComponentSource.INSTALLED
        if installed
        else rows_mod.ComponentSource.NONE,
        installed=installed,
        requires=requires,
        release=release,
        bucket=bucket,
    )


def _target_row(
    platform: str, distribution: str, sdk_requires: str
) -> rows_mod.ComponentRow:
    """一行可更新的适配器，目录最新版自带接口包要求"""
    newest = replace(
        _release_row("0.1.1", _SHA, distribution), sdk_requires=sdk_requires
    )

    return rows_mod.ComponentRow(
        platform=platform,
        distribution=distribution,
        source=rows_mod.ComponentSource.INSTALLED,
        installed="0.1.0",
        requires="",
        release=newest,
        bucket=rows_mod.ComponentBucket.UPGRADABLE,
    )


class TestVersionEntries(unittest.TestCase):
    """版本窗里逐版的读数"""

    def setUp(self) -> None:
        """临时 wheel 目录，0.2.0 那份件在场"""
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self._root = Path(holder.name)
        self._cached = _wheel_on(self._root, "0.2.0")

    def _row(self, installed: str) -> rows_mod.ComponentRow:
        """最新 0.3.0，清单里另有 0.2.0 与 0.1.0 两版"""
        return _multi_row(
            installed,
            _release_row("0.3.0", _SHA),
            _release_row("0.2.0", self._cached),
            _release_row("0.1.0", _SHA),
        )

    def _entries(self, row: rows_mod.ComponentRow) -> tuple[mod.VersionEntry, ...]:
        """按临时目录盘一遍"""
        with patch.object(mod, "WHEELS_DIR", self._root):
            return mod.version_entries(row)

    def test_all_versions_are_listed(self) -> None:
        """清单逐版全摆，最新一版也在里面"""
        entries = self._entries(self._row("0.1.0"))

        self.assertEqual(
            [entry.release.version for entry in entries], ["0.3.0", "0.2.0", "0.1.0"]
        )

    def test_installed_version_is_current(self) -> None:
        """环境里就是这一版即标当前使用"""
        entries = self._entries(self._row("0.1.0"))

        self.assertEqual(entries[2].state, mod.VersionState.CURRENT)

    def test_matching_digest_is_local(self) -> None:
        """盘上那份件指纹对得上目录即算本地有"""
        entries = self._entries(self._row("0.1.0"))

        self.assertEqual(entries[1].state, mod.VersionState.LOCAL)

    def test_wrong_digest_falls_to_network(self) -> None:
        """盘上同名那份件指纹对不上即只能走网络"""
        row = _multi_row(
            "0.1.0",
            _release_row("0.3.0", _SHA),
            _release_row("0.2.0", "f" * 64),
        )

        self.assertEqual(self._entries(row)[1].state, mod.VersionState.NETWORK)

    def test_absent_version_is_network(self) -> None:
        """盘上没有这一版即从网络安装"""
        entries = self._entries(self._row("0.1.0"))

        self.assertEqual(entries[0].state, mod.VersionState.NETWORK)

    def test_no_row_lists_nothing(self) -> None:
        """没有目录行即没有清单可列"""
        row = replace(_multi_row("0.1.0", _release_row("0.1.0", _SHA)), release=None)

        self.assertEqual(self._entries(row), ())


class TestUpdateTarget(unittest.TestCase):
    """更新前先算在场适配器的后果"""

    _RANGE = ">=0.1.0,<0.2.0"

    def _rows(self, installed: str, *versions: str) -> list[rows_mod.ComponentRow]:
        """接口包一行加一只在场适配器，它要求接口包落在 0.1.0 到 0.2.0 之间"""
        sdk = _component("", _SDK, installed, "", *versions)
        adapter = _component(
            str(PlatformCode("tg")), _ADAPTER, "0.1.0", self._RANGE, "0.1.1"
        )

        return [sdk, adapter]

    def test_sdk_row_is_local_without_target(self) -> None:
        """接口包那行只报读数，归本机已有且没有该装的一版"""
        sdk_release = _release_row("0.2.1", _SHA, _SDK)
        catalog = Catalog(sdk=sdk_release, adapters={}, rejects=())
        with (
            patch.object(rows_mod, "installed_adapters", lambda: ()),
            patch.object(rows_mod, "tree_distributions", lambda: {}),
            patch.object(rows_mod, "load_adapter_manifests", lambda: {}),
            patch.object(rows_mod, "installed_version", lambda name: "0.2.0"),
            patch.object(rows_mod, "project_value", lambda key, path: ""),
        ):
            rows = rows_mod.component_rows(catalog)

        sdk = rows[0]
        self.assertEqual(sdk.bucket, rows_mod.ComponentBucket.LOCAL)
        self.assertIsNone(mod.update_target(rows, sdk))

    def test_adapter_row_takes_latest(self) -> None:
        """适配器那行仍取目录最新一版"""
        rows = self._rows("0.1.0", "0.2.0", "0.1.5")
        target = mod.update_target(rows, rows[1])
        if target is None:
            self.fail("适配器那行没交出版本")

        self.assertEqual(target.version, "0.1.1")


class TestBucket(unittest.TestCase):
    """一行组件归到哪一档"""

    def test_newer_online_is_upgradable(self) -> None:
        """在线比本机新即进可更新"""
        self.assertEqual(
            _tg_row("0.1.0", "0.1.1").bucket, rows_mod.ComponentBucket.UPGRADABLE
        )

    def test_same_version_is_local(self) -> None:
        """版本相等即已到位"""
        self.assertEqual(
            _tg_row("0.1.0", "0.1.0").bucket, rows_mod.ComponentBucket.LOCAL
        )

    def test_older_online_is_local(self) -> None:
        """在线比本机旧即不动，不提示降级"""
        self.assertEqual(
            _tg_row("0.2.0", "0.1.0").bucket, rows_mod.ComponentBucket.LOCAL
        )

    def test_absent_package_is_online(self) -> None:
        """本机没在场即只在网络"""
        self.assertEqual(_tg_row("", "0.1.0").bucket, rows_mod.ComponentBucket.ONLINE)

    def test_tree_source_is_local(self) -> None:
        """源码仓挂着且已装包即本机已有，在线再新也不给装"""
        self.assertEqual(
            _tg_row("0.1.0", "0.1.1", tree=True).bucket, rows_mod.ComponentBucket.LOCAL
        )

    def test_tree_source_without_package_is_online(self) -> None:
        """源码仓挂着但没装包即仍算只在网络，还要给装"""
        self.assertEqual(
            _tg_row("", "0.1.0", tree=True).bucket, rows_mod.ComponentBucket.ONLINE
        )

    def test_unreadable_version_is_local(self) -> None:
        """版本串读不懂算本机已有，不拿猜的新版去装"""
        self.assertEqual(
            _tg_row("最新", "0.1.0").bucket, rows_mod.ComponentBucket.LOCAL
        )


class TestSourceReading(unittest.TestCase):
    """来源那行的四档读数"""

    def test_tree_with_package(self) -> None:
        """源码仓挂着且装进了环境即第一档"""
        self.assertEqual(
            _tg_row("0.1.0", "0.1.1", tree=True).source,
            rows_mod.ComponentSource.TREE_INSTALLED,
        )

    def test_tree_without_package(self) -> None:
        """源码仓挂着但环境里没那只包即第二档"""
        self.assertEqual(
            _tg_row("", "0.1.0", tree=True).source,
            rows_mod.ComponentSource.TREE_ONLY,
        )

    def test_package_only(self) -> None:
        """只有环境里那只包即第三档"""
        self.assertEqual(
            _tg_row("0.1.0", "0.1.1").source, rows_mod.ComponentSource.INSTALLED
        )

    def test_absent(self) -> None:
        """两样都没有即第四档"""
        self.assertEqual(_tg_row("", "0.1.0").source, rows_mod.ComponentSource.NONE)


class TestOrigin(unittest.TestCase):
    """一行摆的内容从哪儿取到"""

    _BODY = b"wheel body"

    def setUp(self) -> None:
        """临时 wheel 目录，按点名决定那份件在不在场"""
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self._root = Path(holder.name)

    def _row(
        self,
        source: rows_mod.ComponentSource,
        with_release: bool = True,
        on_disk: bool = False,
    ) -> rows_mod.ComponentRow:
        """一行读数，直链末段就是盘上那个文件名"""
        release = None
        if with_release:
            if on_disk:
                (self._root / "finshin-adapter-tg.whl").write_bytes(self._BODY)
            release = ReleaseRow(
                distribution=_ADAPTER,
                version="0.1.1",
                url="https://example.invalid/finshin-adapter-tg.whl",
                sha256=hashlib.sha256(self._BODY).hexdigest(),
            )

        return rows_mod.ComponentRow(
            platform=str(PlatformCode("tg")),
            distribution=_ADAPTER,
            source=source,
            installed="0.1.0",
            requires="",
            release=release,
            bucket=rows_mod.ComponentBucket.UPGRADABLE,
        )

    def _origin(self, row: rows_mod.ComponentRow) -> mod.ComponentOrigin:
        """按临时目录那份件算来路"""
        with patch.object(mod, "WHEELS_DIR", self._root):
            return mod.source_origin([row], row)

    def test_cached_file_is_the_source(self) -> None:
        """盘上那份件指纹对得上目录即算本机已下载的件"""
        row = self._row(rows_mod.ComponentSource.INSTALLED, on_disk=True)
        self.assertEqual(self._origin(row), mod.ComponentOrigin.WHEEL)

    def test_absent_file_falls_to_catalog(self) -> None:
        """件不在盘上即只能走在线目录"""
        row = self._row(rows_mod.ComponentSource.INSTALLED)
        self.assertEqual(self._origin(row), mod.ComponentOrigin.CATALOG)

    def test_wrong_digest_is_not_the_source(self) -> None:
        """同名那份件指纹对不上即不算本机的件"""
        (self._root / "finshin-adapter-tg.whl").write_bytes(b"other body")
        row = self._row(rows_mod.ComponentSource.INSTALLED)
        self.assertEqual(self._origin(row), mod.ComponentOrigin.CATALOG)

    def test_tree_without_catalog_row(self) -> None:
        """没目录行而源码仓挂着即只有源码仓"""
        for source in (
            rows_mod.ComponentSource.TREE_INSTALLED,
            rows_mod.ComponentSource.TREE_ONLY,
        ):
            row = self._row(source, with_release=False)
            self.assertEqual(self._origin(row), mod.ComponentOrigin.TREE)

    def test_installed_package_without_catalog_row(self) -> None:
        """没目录行而只有环境里那只包即没有可取的内容"""
        row = self._row(rows_mod.ComponentSource.INSTALLED, with_release=False)
        self.assertEqual(self._origin(row), mod.ComponentOrigin.NONE)

    def test_absent_without_catalog_row(self) -> None:
        """本机什么都没有即没有可取的内容"""
        row = self._row(rows_mod.ComponentSource.NONE, with_release=False)
        self.assertEqual(self._origin(row), mod.ComponentOrigin.NONE)


class TestDistributionName(unittest.TestCase):
    """块首行接的发行件名"""

    def test_tree_declaration_names_the_row(self) -> None:
        """挂载仓那份声明交得出名，没装包也不空着"""
        self.assertEqual(_tg_row("", "0.1.0", tree=True).distribution, _ADAPTER)


class TestUpdateTargets(unittest.TestCase):
    """一键更新的那批目录行"""

    def test_local_row_excluded(self) -> None:
        """本机已有的行不进差集"""
        self.assertEqual(mod.update_targets([_tg_row("0.1.0", "0.1.0")]), [])

    def test_upgradable_row_included(self) -> None:
        """可更新的行进差集，交的是目录行自带的直链与指纹"""
        sdk = _component("", _SDK, "0.1.0", "", "0.1.0")
        adapter = _component(str(PlatformCode("tg")), _ADAPTER, "0.1.0", "", "0.1.1")
        targets = mod.update_targets([sdk, adapter])
        self.assertEqual([release.version for release in targets], ["0.1.1"])
        self.assertEqual([release.distribution for release in targets], [_ADAPTER])

    def test_online_row_excluded(self) -> None:
        """本机没装过的不进一键，装哪个平台由逐行的按钮定"""
        self.assertEqual(mod.update_targets([_tg_row("", "0.1.0")]), [])

    def test_blocked_target_excluded(self) -> None:
        """目标版被挡的那行不进一键，别的行照收"""
        sdk = _component("", _SDK, "0.2.0", "", "0.2.0")
        rows = [
            sdk,
            _target_row(str(PlatformCode("tg")), _ADAPTER, "<0.2.0"),
            _target_row("qq", "finshin-adapter-qq", ">=0.2.0"),
        ]

        self.assertEqual(
            [item.distribution for item in mod.update_targets(rows)],
            ["finshin-adapter-qq"],
        )


class TestInstallBlocked(unittest.TestCase):
    """接口包不在要求的区间内时适配器那颗不给装，并交出那句下一步"""

    _TARGET = _release_row("0.1.1", _SHA)

    def test_absent_sdk_blocks_the_adapter(self) -> None:
        """接口包没装上即挡住，那句让重开补装"""
        rows = _rows("", "")
        self.assertEqual(
            mod._install_blocked(rows, _adapter_row(rows), self._TARGET),
            "接口包没装上，重开会补装",
        )

    def test_installed_sdk_frees_the_adapter(self) -> None:
        """接口包在场即放行"""
        rows = _rows("0.1.0", "")
        self.assertEqual(
            mod._install_blocked(rows, _adapter_row(rows), self._TARGET), ""
        )

    def test_sdk_below_range_blocks(self) -> None:
        """接口包在场但够不到适配器要求的下限，那句指向新版程序"""
        requires = {str(PlatformCode("tg")): ">=9.9.9"}
        with patch.object(rows_mod, "_declared_requires", lambda: requires):
            rows = _rows("0.1.0", "0.1.0")
        self.assertEqual(
            mod._install_blocked(rows, _adapter_row(rows), self._TARGET),
            "接口包太旧，新版程序才带",
        )

    def test_sdk_over_ceiling_blocks(self) -> None:
        """接口包高出适配器写的上限，那句换成接口包太新"""
        requires = {str(PlatformCode("tg")): "<0.0.1"}
        with patch.object(rows_mod, "_declared_requires", lambda: requires):
            rows = _rows("0.1.0", "0.1.0")
        self.assertEqual(
            mod._install_blocked(rows, _adapter_row(rows), self._TARGET),
            "接口包太新，适配器等新版",
        )

    def test_sdk_in_range_frees(self) -> None:
        """接口包落在要求的区间之内即放行"""
        requires = {str(PlatformCode("tg")): ">=0.1.0,<0.2.0"}
        with patch.object(rows_mod, "_declared_requires", lambda: requires):
            rows = _rows("0.1.5", "0.1.0")
        self.assertEqual(
            mod._install_blocked(rows, _adapter_row(rows), self._TARGET), ""
        )

    def test_target_version_requirement_wins(self) -> None:
        """要装那一版自带要求即按它判，同一行按已装声明判本来放行"""
        requires = {str(PlatformCode("tg")): ">=0.1.0,<0.2.0"}
        with patch.object(rows_mod, "_declared_requires", lambda: requires):
            rows = _rows("0.1.0", "0.1.0")
        row = _adapter_row(rows)
        target = replace(self._TARGET, sdk_requires="<0.0.1")

        self.assertEqual(
            mod.release_blocked(rows, row, target), "接口包太新，适配器等新版"
        )
        self.assertEqual(mod.release_blocked(rows, row, self._TARGET), "")

    def test_requires_line_keeps_both_bounds(self) -> None:
        """要求那一行把上下限原样带出来"""
        requires = {str(PlatformCode("tg")): ">=0.1.0,<0.2.0"}
        with (
            patch.object(rows_mod, "_declared_requires", lambda: requires),
            patch.object(mod, "installed_version", lambda name: "0.2.0"),
        ):
            text = mod.deps_text(_adapter_row(_rows("0.2.0", "0.1.0")))
        self.assertEqual(text, ">=0.1.0,<0.2.0，本机接口包 0.2.0 未满足")

    def test_requires_line_without_sdk(self) -> None:
        """本机没装接口包时要求行照实说没装上"""
        requires = {str(PlatformCode("tg")): ">=0.1.0,<0.2.0"}
        with (
            patch.object(rows_mod, "_declared_requires", lambda: requires),
            patch.object(mod, "installed_version", lambda name: ""),
        ):
            text = mod.deps_text(_adapter_row(_rows("", "0.1.0")))
        self.assertEqual(text, ">=0.1.0,<0.2.0，接口包没装上")


class TestPresentPlatforms(unittest.TestCase):
    """选窗认的在场平台"""

    def test_lists_installed_platform_only(self) -> None:
        """已装适配器的那一平台进表，接口包那行不进"""
        with ExitStack() as stack:
            for patcher in (
                patch.object(
                    rows_mod, "installed_adapters", lambda: (_adapter("0.1.0"),)
                ),
                patch.object(rows_mod, "tree_distributions", lambda: {}),
                patch.object(rows_mod, "load_adapter_manifests", lambda: {}),
                patch.object(rows_mod, "installed_version", lambda name: "0.1.0"),
                patch.object(rows_mod, "project_value", lambda key, path: ""),
            ):
                stack.enter_context(patcher)
            self.assertEqual(rows_mod.present_platforms(), frozenset({"tg"}))

    def test_tree_without_package_is_absent(self) -> None:
        """源码仓挂着但没装包的平台不进表"""
        with ExitStack() as stack:
            for patcher in (
                patch.object(rows_mod, "installed_adapters", lambda: ()),
                patch.object(
                    rows_mod,
                    "tree_distributions",
                    lambda: {PlatformCode("tg"): _ADAPTER},
                ),
                patch.object(rows_mod, "load_adapter_manifests", lambda: {}),
                patch.object(rows_mod, "installed_version", lambda name: ""),
                patch.object(rows_mod, "project_value", lambda key, path: ""),
            ):
                stack.enter_context(patcher)
            self.assertEqual(rows_mod.present_platforms(), frozenset())


if __name__ == "__main__":
    unittest.main()
