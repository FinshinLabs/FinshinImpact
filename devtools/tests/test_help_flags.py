"""插件命令输入与帮助渲染的单元测试

- 覆盖帮助图条目行与插件块之间的空行
- 覆盖单命令帮助的开关行与参数行渲染
- 覆盖用法提示行的命令名打头
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from bundled._shared.messages import BotMessage  # noqa: E402
from bundled.help import _services  # noqa: E402
from finshin_sdk.domain import CommandHelp, FlagHelp  # noqa: E402


class TestMenuEntries(unittest.TestCase):
    """帮助图的命令条目与开关条目"""

    def _entries(self, flags: tuple[FlagHelp, ...]) -> list[tuple[str, str, str]]:
        command = CommandHelp(cmd="md", desc="图片输出", flags=flags)
        section = SimpleNamespace(section="", note="", commands=(command,))
        manifest = SimpleNamespace(declaration=SimpleNamespace(help=(section,)))
        with patch.object(_services, "enabled_manifests", lambda path: [manifest]):
            return _services._build_help_menu()[2]

    def test_flags_follow_command_one_entry_each(self) -> None:
        entries = self._entries(
            (FlagHelp("-i", "图片输入"), FlagHelp("-t", "输出速度", 1.0))
        )
        self.assertEqual(
            entries[-5:],
            [
                ("command", "md", "图片输出"),
                ("flag", "-i", "图片输入"),
                ("flag", "-t 1.0", "输出速度"),
                ("gap", "", ""),
                ("section", "未完待续", ""),
            ],
        )

    def test_command_without_flags_adds_no_entry(self) -> None:
        entries = self._entries(())
        self.assertEqual(
            entries[-3:],
            [
                ("command", "md", "图片输出"),
                ("gap", "", ""),
                ("section", "未完待续", ""),
            ],
        )

    def test_blank_row_leads_each_plugin_block(self) -> None:
        entries = self._entries(())
        self.assertEqual(entries[2], ("gap", "", ""))
        self.assertEqual(entries[3][0], "command")

    def test_empty_manifest_adds_no_extra_blank_row(self) -> None:
        manifest = SimpleNamespace(declaration=SimpleNamespace(help=()))
        with patch.object(_services, "enabled_manifests", lambda path: [manifest]):
            entries = _services._build_help_menu()[2]
        self.assertEqual(entries.count(("gap", "", "")), 1)

    def test_spec_registered_for_command(self) -> None:
        flags = (FlagHelp("-i", "图片输入"),)
        command = CommandHelp(cmd="md", desc="图片输出", flags=flags)
        section = SimpleNamespace(section="", note="", commands=(command,))
        manifest = SimpleNamespace(declaration=SimpleNamespace(help=(section,)))
        with patch.object(_services, "enabled_manifests", lambda path: [manifest]):
            help_list, specs, _ = _services._build_help_menu()
        self.assertEqual(help_list["md"], "图片输出")
        self.assertEqual(specs["md"].flags, flags)

    def test_digest_follows_flag_note(self) -> None:
        with patch.object(
            _services, "_display_order", self._entries((FlagHelp("-i", "甲"),))
        ):
            first = _services._menu_digest()
        with patch.object(
            _services, "_display_order", self._entries((FlagHelp("-i", "乙"),))
        ):
            second = _services._menu_digest()
        self.assertNotEqual(first, second)

    def test_digest_follows_flag_value_name(self) -> None:
        with patch.object(
            _services, "_display_order", self._entries((FlagHelp("-t", "甲"),))
        ):
            first = _services._menu_digest()
        with patch.object(
            _services,
            "_display_order",
            self._entries((FlagHelp("-t", "甲", 1.0),)),
        ):
            second = _services._menu_digest()
        self.assertNotEqual(first, second)

    def test_digest_follows_style_change(self) -> None:
        """行距或配色档一变即重画"""
        for attr, value in (("line_spacing", 26), ("palette_colors", 32)):
            with self.subTest(attr=attr):
                first = _services._menu_digest()
                with patch.object(_services._HELP, attr, value):
                    second = _services._menu_digest()
                self.assertNotEqual(first, second)


class _SpecStubMixin(unittest.TestCase):
    """按固定命令声明挂上 help_list 与 command_specs"""

    def setUp(self) -> None:
        help_list = {
            "md": "图片输出",
            "push": "推送消息",
            "convert": "格式转换",
            "history": "显示历史记录",
        }
        command_specs = {
            "md": CommandHelp(
                cmd="md", desc="图片输出", flags=(FlagHelp("-i", "图片输入"),)
            ),
            "push": CommandHelp(cmd="push", desc="推送消息", args="文件路径"),
            "convert": CommandHelp(
                cmd="convert",
                desc="格式转换",
                flags=(FlagHelp("-t", "输出速度", 1.0),),
            ),
        }
        for name, value in (
            ("help_list", help_list),
            ("command_specs", command_specs),
        ):
            patcher = patch.object(_services, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)


class TestUsageLine(_SpecStubMixin):
    """单命令帮助的开关行与参数行"""

    def test_help_flag_leads_and_declared_follow(self) -> None:
        text = _services.resolve_single_help("md")
        self.assertIn("-h", text)
        self.assertLess(text.index("-h"), text.index("-i"))

    def test_flag_note_shows_on_its_own_line(self) -> None:
        text = _services.resolve_single_help("md")
        self.assertIn("-h 看用法", text)
        self.assertIn("-i 图片输入", text)

    def test_help_text_shapes(self) -> None:
        """带参数、带值开关与没声明的命令各出对应帮助"""
        cases = (
            ("push", "推送消息\n可用参数：文件路径\n可用开关：\n-h 看用法"),
            ("convert", "格式转换\n可用开关：\n-h 看用法\n-t 1.0 输出速度"),
            ("history", "显示历史记录"),
        )
        for cmd, want in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual(_services.resolve_single_help(cmd), want)

    def test_undeclared_args_leave_no_line(self) -> None:
        self.assertNotIn("可用参数", _services.resolve_single_help("md"))

    def test_unknown_name_is_format_error(self) -> None:
        self.assertEqual(
            _services.resolve_single_help("nope"),
            BotMessage.CMD_FORMAT_ERROR,
        )


class TestUsageHint(_SpecStubMixin):
    """多余输入回执的用法提示"""

    def test_hint_shapes(self) -> None:
        """提示行首带命令名，参数与开关按声明出"""
        cases = (
            ("convert", "/convert 用法错误\n可用开关：\n-h 看用法\n-t 1.0 输出速度"),
            ("push", "/push 用法错误\n可用参数：文件路径\n可用开关：\n-h 看用法"),
        )
        for cmd, want in cases:
            with self.subTest(cmd=cmd):
                self.assertEqual(_services.resolve_usage_hint(cmd), want)

    def test_hint_without_spec_is_format_error(self) -> None:
        self.assertEqual(
            _services.resolve_usage_hint("history"),
            BotMessage.CMD_FORMAT_ERROR,
        )


if __name__ == "__main__":
    unittest.main()
