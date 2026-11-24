"""插件代码声明读取的单元测试

- 外部插件名与接口包要求取自家项目声明
- 代码声明只执行 finshin_sdk 导入、赋值与 def
- 每次重新读取，不执行插件入口，也不缓存
- 缺文件、形状错误与接口包区间不满足均拒收
- 引导期与运行期按相同规则读取
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from finshin_sdk.domain import CommandRole  # noqa: E402
from services.env_setup import deps_manifest  # noqa: E402
from system import plugin_declaration  # noqa: E402
from system.plugin_roster import (  # noqa: E402
    BUNDLED_PLUGINS_PKG,
    INSTALLED_PLUGINS_PKG,
)
from utils.plugin import _manifest  # noqa: E402

_SDK_PIN = "finshin-sdk>=0.2.0,<0.4.0"
_HEAD = """from finshin_sdk.domain import CommandHelp, PluginDeclaration, SectionHelp

TITLE = "样例"

DECLARATION = PluginDeclaration(
    title=TITLE,
    summary="代码声明用例",
    assets=(),
    help=(SectionHelp(section="样例", commands=(CommandHelp(cmd="demo", desc="演示"),)),),
)
"""


def _write_code(plugin_dir: Path, source: str = _HEAD) -> None:
    """写一份插件代码声明"""
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "_declaration.py").write_text(source, encoding="utf-8")


def _write_project(
    plugin_dir: Path,
    *,
    name: str | None = None,
    deps: tuple[str, ...] = (_SDK_PIN,),
) -> None:
    """写一份外部插件项目声明"""
    project_name = name or f"finshin-plugin-{plugin_dir.name}"
    rendered = ", ".join(f'"{pin}"' for pin in deps)
    (plugin_dir / "pyproject.toml").write_text(
        f'[project]\nname = "{project_name}"\nversion = "0"\n'
        f"dependencies = [{rendered}]\n",
        encoding="utf-8",
    )


def _write_external(
    root: Path,
    name: str,
    *,
    source: str = _HEAD,
    project_name: str | None = None,
    deps: tuple[str, ...] = (_SDK_PIN,),
) -> Path:
    """摆一只外部插件"""
    plugin_dir = root / name
    _write_code(plugin_dir, source)
    _write_project(plugin_dir, name=project_name, deps=deps)
    return plugin_dir


def _names(root: Path, pkg: str) -> tuple[list[str], list[str]]:
    """分别取引导期与运行期认到的插件名"""
    rows = deps_manifest.load_manifests([(root, pkg)])
    manifests = _manifest._load_manifests(root, pkg, False)
    return [row.name for row in rows], list(manifests)


class PluginDeclarationCase(unittest.TestCase):
    """代码声明读取的公共脚手架"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _reject(self, source: str, expected: str) -> None:
        plugin_dir = self.root / "demo"
        _write_code(plugin_dir, source)
        with self.assertRaises(plugin_declaration.PluginDeclarationError) as caught:
            plugin_declaration._read_code_declaration(plugin_dir)
        message = str(caught.exception)
        self.assertIn("_declaration.py:", message)
        self.assertIn(expected, message)


class TestPluginPackageReads(PluginDeclarationCase):
    """两处读取侧共用拆件规则"""

    def test_external_name_comes_from_project(self) -> None:
        """合法项目名与目录后缀相同，两侧都认目录名"""
        _write_external(self.root, "echo", deps=(_SDK_PIN, "markdown==3.10.2"))

        self.assertEqual(_names(self.root, INSTALLED_PLUGINS_PKG), (["echo"], ["echo"]))

    def test_bad_project_name_is_refused(self) -> None:
        """缺前缀或后缀与目录不同，两侧都不认"""
        for name in ("echo", "finshin-plugin-other"):
            with self.subTest(name=name):
                _write_external(self.root, "echo", project_name=name)

                self.assertEqual(_names(self.root, INSTALLED_PLUGINS_PKG), ([], []))

    def test_missing_project_is_refused(self) -> None:
        """外部插件只有代码声明时两侧都不认"""
        _write_code(self.root / "echo")

        self.assertEqual(_names(self.root, INSTALLED_PLUGINS_PKG), ([], []))

    def test_missing_code_declaration_is_skipped(self) -> None:
        """缺代码声明的目录不进入两张表"""
        plugin_dir = self.root / "echo"
        plugin_dir.mkdir()
        _write_project(plugin_dir)

        self.assertEqual(_names(self.root, INSTALLED_PLUGINS_PKG), ([], []))

    def test_bundled_name_comes_from_directory(self) -> None:
        """随包插件没有项目声明，名字直接取目录名"""
        _write_code(self.root / "help")

        self.assertEqual(_names(self.root, BUNDLED_PLUGINS_PKG), (["help"], ["help"]))

    def test_bundled_skips_sdk_requirement(self) -> None:
        """随包插件不读接口包依赖，也不做区间判定"""
        _write_code(self.root / "help")
        with (
            patch.object(plugin_declaration, "requires_of") as requires_of,
            patch.object(plugin_declaration, "requires_met") as requires_met,
        ):
            self.assertEqual(
                _names(self.root, BUNDLED_PLUGINS_PKG), (["help"], ["help"])
            )

        requires_of.assert_not_called()
        requires_met.assert_not_called()


class TestPluginSdkRange(PluginDeclarationCase):
    """外部插件按自家接口包要求放行"""

    def setUp(self) -> None:
        super().setUp()
        patcher = patch.object(plugin_declaration, "SDK_VERSION", "0.3.0")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_sdk_requirement_is_refused(self) -> None:
        """依赖表里没有 finshin-sdk 行，两侧都不认"""
        _write_external(self.root, "echo", deps=("markdown==3.10.2",))

        self.assertEqual(_names(self.root, INSTALLED_PLUGINS_PKG), ([], []))

    def test_out_of_range_is_refused_and_logged(self) -> None:
        """本机不在区间内即不加载，日志带插件名、要求与本机版本"""
        required = ">=0.4.0,<0.5.0"
        _write_external(self.root, "echo", deps=(f"finshin-sdk{required}",))
        with patch.object(_manifest._logger, "info") as log:
            self.assertEqual(_names(self.root, INSTALLED_PLUGINS_PKG), ([], []))

        message = log.call_args.args[0]
        self.assertIn("echo", message)
        self.assertIn(required, message)
        self.assertIn("0.3.0", message)

    def test_inside_range_is_allowed(self) -> None:
        """本机落在要求区间内，两侧都放行"""
        _write_external(self.root, "echo", deps=("finshin-sdk>=0.3.0,<0.4.0",))

        self.assertEqual(_names(self.root, INSTALLED_PLUGINS_PKG), (["echo"], ["echo"]))


class TestCodePolicy(PluginDeclarationCase):
    """顶层语句、默认值与装饰器的准入规则"""

    def test_sdk_imports_assignments_and_functions_pass(self) -> None:
        """接口包导入、普通赋值与本地函数都可用"""
        source = """from finshin_sdk.domain import CommandHelp, PluginDeclaration

def mark(value):
    return value

@mark
def default():
    return "默认值"

DECLARATION = PluginDeclaration(title="样例", summary=default(), assets=(), help=())
"""
        plugin_dir = self.root / "demo"
        _write_code(plugin_dir, source)

        declaration = plugin_declaration._read_code_declaration(plugin_dir)

        self.assertEqual(declaration.summary, "默认值")

    def test_non_sdk_import_is_refused(self) -> None:
        self._reject("import os\nDECLARATION = None\n", "只许导入 finshin_sdk")

    def test_top_level_call_is_refused(self) -> None:
        self._reject("print('跑一下')\n", "顶层只许")

    def test_nested_import_is_refused(self) -> None:
        self._reject("def load():\n    import os\n", "只许在顶层导入")

    def test_private_name_is_refused(self) -> None:
        self._reject("_hidden = 1\n", "赋值目标只许普通名字")

    def test_foreign_default_call_is_refused(self) -> None:
        self._reject("def load(value=open('x')):\n    return value\n", "不许调用 open")

    def test_foreign_decorator_is_refused(self) -> None:
        self._reject("@staticmethod\ndef load():\n    pass\n", "不许访问 staticmethod")


class TestDeclarationShape(PluginDeclarationCase):
    """加载记录各层容器的真实形状"""

    def test_full_shape_is_preserved(self) -> None:
        """标题、资源、命令、开关与权限原样保留"""
        source = """from finshin_sdk.domain import CommandHelp, CommandRole, FlagHelp, PluginDeclaration, SectionHelp

DECLARATION = PluginDeclaration(
    title="工具",
    summary="一组工具",
    assets=("playwright chromium",),
    help=(SectionHelp(section="样例", note="说明", commands=(CommandHelp(
        cmd="demo",
        desc="演示",
        args="内容",
        role=CommandRole.ADMIN,
        flags=(FlagHelp("-n", "次数", 2), FlagHelp("-i", "开关")),
    ),)),),
)
"""
        plugin_dir = self.root / "demo"
        _write_code(plugin_dir, source)

        declaration = plugin_declaration._read_code_declaration(plugin_dir)
        command = declaration.help[0].commands[0]

        self.assertEqual(declaration.assets, ("playwright chromium",))
        self.assertEqual(
            (command.cmd, command.args, command.role),
            ("demo", "内容", CommandRole.ADMIN),
        )
        self.assertEqual(
            [(flag.name, flag.default) for flag in command.flags],
            [("-n", 2), ("-i", None)],
        )

    def test_wrong_containers_are_refused(self) -> None:
        """列表代替元组、错误段类型与错误命令类型均拒收"""
        sources = (
            'PluginDeclaration(title="a", summary="b", assets=[], help=())',
            'PluginDeclaration(title="a", summary="b", assets=(), help=[SectionHelp(section="x")])',
            'PluginDeclaration(title="a", summary="b", assets=(), help=(None,))',
            'PluginDeclaration(title="a", summary="b", assets=(), help=(SectionHelp(section="x", commands=(None,)),))',
        )
        for expression in sources:
            with self.subTest(expression=expression):
                self._reject(
                    f"from finshin_sdk.domain import PluginDeclaration, SectionHelp\nDECLARATION = {expression}\n",
                    "必须",
                )

    def test_bad_flag_default_is_refused(self) -> None:
        """真假值、空文本与数组不能当开关默认值"""
        for default in ("True", '""', "[]"):
            with self.subTest(default=default):
                source = f"""from finshin_sdk.domain import CommandHelp, FlagHelp, PluginDeclaration, SectionHelp

DECLARATION = PluginDeclaration(
    title="a",
    summary="b",
    assets=(),
    help=(SectionHelp(section="x", commands=(CommandHelp(
        cmd="demo", desc="演示", flags=(FlagHelp("-n", "次数", {default}),)
    ),)),),
)
"""
                self._reject(source, "开关默认值")

    def test_bad_flag_name_is_refused(self) -> None:
        """开关名不带短横线即拒收"""
        source = """from finshin_sdk.domain import CommandHelp, FlagHelp, PluginDeclaration, SectionHelp

DECLARATION = PluginDeclaration(
    title="a",
    summary="b",
    assets=(),
    help=(SectionHelp(section="x", commands=(CommandHelp(
        cmd="demo", desc="演示", flags=(FlagHelp("n", "次数"),)
    ),)),),
)
"""
        self._reject(source, "开关名或说明不合法")


class TestReadIsolation(PluginDeclarationCase):
    """声明读取不缓存，也不执行插件入口"""

    def test_repeated_reads_see_file_changes(self) -> None:
        """同一文件改过标题后，下一次读取立即拿到新值"""
        plugin_dir = self.root / "demo"
        _write_code(plugin_dir)

        first = plugin_declaration._read_code_declaration(plugin_dir)
        _write_code(plugin_dir, _HEAD.replace('TITLE = "样例"', 'TITLE = "新标题"'))
        second = plugin_declaration._read_code_declaration(plugin_dir)

        self.assertEqual((first.title, second.title), ("样例", "新标题"))

    def test_plugin_init_is_not_executed(self) -> None:
        """入口文件故意抛错也不影响代码声明读取"""
        plugin_dir = self.root / "demo"
        _write_code(plugin_dir)
        (plugin_dir / "__init__.py").write_text(
            "raise RuntimeError('不许执行')\n", encoding="utf-8"
        )

        declaration = plugin_declaration._read_code_declaration(plugin_dir)

        self.assertEqual(declaration.title, "样例")

    def test_runtime_error_reports_source_line(self) -> None:
        """声明执行报错时指出文件内对应行"""
        source = """from finshin_sdk.domain import PluginDeclaration

def build():
    return 1 / 0

DECLARATION = PluginDeclaration(title=build(), summary="b", assets=(), help=())
"""
        plugin_dir = self.root / "demo"
        _write_code(plugin_dir, source)
        with self.assertRaises(plugin_declaration.PluginDeclarationError) as caught:
            plugin_declaration._read_code_declaration(plugin_dir)

        self.assertIn("_declaration.py:4:", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
