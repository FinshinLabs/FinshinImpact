"""插件加载记录与档位的单元测试

- 代码声明只交标题、说明、资源与帮助
- 恒启用与加载档位来自随包表
- 引导期与运行期在排序和读取字段上一致
- 同名插件以随包那一行为准
- 外部插件名字与依赖取自家项目声明
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from finshin_sdk.domain import CommandHelp, PluginDeclaration, SectionHelp  # noqa: E402
from services.env_setup import deps_manifest  # noqa: E402
from system.plugin_roster import (  # noqa: E402
    BUNDLED_PLUGINS_PKG,
    INSTALLED_PLUGINS_DIR,
    INSTALLED_PLUGINS_PKG,
)
from utils.plugin import _manifest  # noqa: E402


def _write(root: Path, name: str, title: str | None = None) -> None:
    """在目录下造一份代码声明"""
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True)
    display = title if title is not None else name
    (plugin_dir / "_declaration.py").write_text(
        "from finshin_sdk.domain import PluginDeclaration\n"
        f'DECLARATION = PluginDeclaration(title="{display}", '
        'summary="外部插件", assets=(), help=())\n',
        encoding="utf-8",
    )


def _write_dependency(root: Path, name: str) -> None:
    """在外部插件目录里补一份只交代依赖的声明"""
    target = root / name / "pyproject.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f'[project]\nname = "finshin-plugin-{name}"\nversion = "0"\n'
        'dependencies = ["finshin-sdk>=0.2.0,<0.4.0", "markdown==3.10.2"]\n',
        encoding="utf-8",
    )


class TestEnabledOrder(unittest.TestCase):
    """运行期读取：随包表定恒启用与档位"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for name in ("extra", "help", "AI"):
            _write(self.root, name)
        patcher = patch.object(
            _manifest, "_plugins_roots", lambda: [(self.root, "bundled")]
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_bundled_enabled_without_state(self) -> None:
        """未勾选就不启用，随包表里的三只除外"""
        picked = _manifest.enabled_manifests(self.root / "profile.json")

        self.assertEqual([m.name for m in picked], ["help", "AI"])

    def test_manifest_has_only_declared_dto_fields(self) -> None:
        """加载记录只保留名字、模块、依赖与代码声明"""
        picked = _manifest.enabled_manifests(self.root / "profile.json")

        self.assertEqual(
            [field for field in picked[0].__dataclass_fields__],
            ["name", "module", "deps", "declaration"],
        )

    def test_external_between_bundled(self) -> None:
        """表外插件一律常规档，排在最先档之后最后档之前"""
        state = self.root / "profile.json"
        state.write_text('{"plugins": {"enabled": ["extra"]}}', encoding="utf-8")

        picked = _manifest.enabled_manifests(state)

        self.assertEqual([m.name for m in picked], ["help", "extra", "AI"])


class TestGuideRead(unittest.TestCase):
    """引导期读取：字段与排序规则同运行期"""

    def test_table_orders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("extra", "help", "AI"):
                _write(root, name)

            rows = deps_manifest.load_manifests([(root, BUNDLED_PLUGINS_PKG)])

            self.assertEqual([row.name for row in rows], ["AI", "help", "extra"])

    def test_bundled_grouped_before_external(self) -> None:
        """随包表里的三只成组在前，表外的名字再靠前也不插进来"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("aardvark", "help", "grant", "AI"):
                _write(root, name)

            rows = deps_manifest.load_manifests([(root, BUNDLED_PLUGINS_PKG)])

            self.assertEqual(
                [row.name for row in rows], ["AI", "grant", "help", "aardvark"]
            )

    def test_groups_order_by_pinyin_of_title(self) -> None:
        """档位表只管命令抢占先后，行序另按显示名排"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            titled = (
                ("help", "权限授权"),
                ("grant", "AI 对话"),
                ("ping_a", "帮助"),
                ("ping_b", "撞名甲"),
            )
            for name, title in titled:
                _write(root, name, title)

            rows = deps_manifest.load_manifests([(root, BUNDLED_PLUGINS_PKG)])

            self.assertEqual(
                [row.declaration.title for row in rows],
                ["AI 对话", "权限授权", "帮助", "撞名甲"],
            )

    def test_blank_title_falls_back_to_name(self) -> None:
        """标题留空时按插件名排显示位"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root, "zeta", "")
            _write(root, "alpha", "Zebra")

            rows = deps_manifest.load_manifests([(root, BUNDLED_PLUGINS_PKG)])

            self.assertEqual([row.name for row in rows], ["alpha", "zeta"])


class TestGuideRoots(unittest.TestCase):
    """引导期根表：随包在前，外部目录按项目根拼"""

    def test_installed_dir_enters_roots_when_present(self) -> None:
        """外部目录存在才进根表"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            installed = base / INSTALLED_PLUGINS_DIR

            with patch.object(deps_manifest, "ROOT_DIR", base):
                names = [pkg for _, pkg in deps_manifest.plugins_roots()]
                self.assertEqual(names, [BUNDLED_PLUGINS_PKG])

                installed.mkdir(parents=True)
                names = [pkg for _, pkg in deps_manifest.plugins_roots()]

            self.assertEqual(names, [BUNDLED_PLUGINS_PKG, INSTALLED_PLUGINS_PKG])

    def test_bundled_row_wins_same_name(self) -> None:
        """两根目录同名时只留随包那一行"""
        with tempfile.TemporaryDirectory() as tmp:
            bundled = Path(tmp) / BUNDLED_PLUGINS_PKG
            installed = Path(tmp) / INSTALLED_PLUGINS_DIR
            _write(bundled, "dup", "随包")
            _write(installed, "dup", "外部")
            _write_dependency(installed, "dup")

            rows = deps_manifest.load_manifests(
                [(bundled, BUNDLED_PLUGINS_PKG), (installed, INSTALLED_PLUGINS_PKG)]
            )

            self.assertEqual([row.declaration.title for row in rows], ["随包"])

    def test_shadowed_row_carries_winner_name(self) -> None:
        """被顶掉的那一份连同赢家的名字一起交出来"""
        with tempfile.TemporaryDirectory() as tmp:
            bundled = Path(tmp) / BUNDLED_PLUGINS_PKG
            installed = Path(tmp) / INSTALLED_PLUGINS_DIR
            _write(bundled, "dup", "随包")
            _write(installed, "dup", "外部")
            _write_dependency(installed, "dup")

            losers = deps_manifest.shadowed_manifests(
                [(bundled, BUNDLED_PLUGINS_PKG), (installed, INSTALLED_PLUGINS_PKG)]
            )

            self.assertEqual(
                [(row.declaration.title, winner) for row, winner in losers],
                [("外部", "dup")],
            )

            quiet = Path(tmp) / "single"
            _write(quiet, "only", "独一份")
            _write_dependency(quiet, "only")
            self.assertEqual(
                deps_manifest.shadowed_manifests(
                    [(bundled, BUNDLED_PLUGINS_PKG), (quiet, INSTALLED_PLUGINS_PKG)]
                ),
                [],
            )


class TestExternalDependencies(unittest.TestCase):
    """外部插件的库从自家声明的依赖表取"""

    def test_libs_come_from_the_own_declaration(self) -> None:
        """两份读取侧都取项目声明里的依赖表"""
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / INSTALLED_PLUGINS_DIR
            _write(installed, "echo", "回声")
            _write_dependency(installed, "echo")

            rows = deps_manifest.load_manifests([(installed, INSTALLED_PLUGINS_PKG)])
            picked = _manifest._load_manifests(installed, INSTALLED_PLUGINS_PKG, False)

            self.assertEqual(
                [row.deps for row in rows],
                [("finshin-sdk>=0.2.0,<0.4.0", "markdown==3.10.2")],
            )
            self.assertEqual(
                picked["echo"].deps,
                ("finshin-sdk>=0.2.0,<0.4.0", "markdown==3.10.2"),
            )

    def test_missing_own_declaration_is_refused(self) -> None:
        """只有代码声明、没写自家依赖声明，两份读取侧都整份不放行"""
        with tempfile.TemporaryDirectory() as tmp:
            installed = Path(tmp) / INSTALLED_PLUGINS_DIR
            _write(installed, "echo", "回声")

            self.assertEqual(
                deps_manifest.load_manifests([(installed, INSTALLED_PLUGINS_PKG)]), []
            )
            self.assertEqual(
                _manifest._load_manifests(installed, INSTALLED_PLUGINS_PKG, False), {}
            )

    def test_bundled_needs_no_own_declaration(self) -> None:
        """随包那档的库在根声明里，目录里没有依赖声明照样进表"""
        with tempfile.TemporaryDirectory() as tmp:
            bundled = Path(tmp) / BUNDLED_PLUGINS_PKG
            _write(bundled, "help")

            rows = deps_manifest.load_manifests([(bundled, BUNDLED_PLUGINS_PKG)])

            self.assertEqual([row.deps for row in rows], [()])


class TestCatalogDigest(unittest.TestCase):
    """目录指纹只随身份、依赖与资源变化"""

    def _manifest(self, name: str, deps: tuple[str, ...], assets: tuple[str, ...]):
        declaration = PluginDeclaration(
            title=name,
            summary="摘要",
            assets=assets,
            help=(
                SectionHelp(
                    section="样例", commands=(CommandHelp(cmd=name, desc="演示"),)
                ),
            ),
        )
        from finshin_sdk.dto import PluginManifestDTO

        return PluginManifestDTO(
            name=name, module=f"bundled.{name}", deps=deps, declaration=declaration
        )

    def test_ignores_title_help_and_row_order(self) -> None:
        """标题、帮助与行序变化不改目录指纹"""
        first = self._manifest("demo", ("foo==1",), ("asset",))
        second = self._manifest("other", (), ())
        changed = self._manifest("demo", ("foo==1",), ("asset",))
        changed = type(changed)(
            name=changed.name,
            module=changed.module,
            deps=changed.deps,
            declaration=type(changed.declaration)(
                title="新标题",
                summary="新摘要",
                assets=changed.declaration.assets,
                help=(),
            ),
        )

        self.assertEqual(
            deps_manifest.catalog_digest([first, second]),
            deps_manifest.catalog_digest([changed, second]),
        )

    def test_follows_name_dependencies_and_assets(self) -> None:
        """身份、依赖或资源任一变化都改指纹"""
        base = self._manifest("demo", ("foo==1",), ("asset",))
        variants = (
            self._manifest("other", ("foo==1",), ("asset",)),
            self._manifest("demo", ("foo==2",), ("asset",)),
            self._manifest("demo", ("foo==1",), ("other",)),
        )

        for variant in variants:
            with self.subTest(variant=variant):
                self.assertNotEqual(
                    deps_manifest.catalog_digest([base]),
                    deps_manifest.catalog_digest([variant]),
                )


if __name__ == "__main__":
    unittest.main()
