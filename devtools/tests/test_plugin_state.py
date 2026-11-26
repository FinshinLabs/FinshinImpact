"""实例插件状态读写的单元测试

- 自描述文件不在、读不出或没有 plugins 块交出 None，代表实例从未保存过插件选择
- 块在但启用键缺失交出空集，与没这一块分得开
- 启用集里非串的成员按字面值收
- 目录指纹缺失、损坏或整块不在都交出空串
- 写状态只替换 plugins 块，自描述文件其余字段原样保留
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.plugin_state import (  # noqa: E402
    StateKeys,
    load_instance_catalog,
    load_instance_enabled,
    save_state,
)


class TestPluginState(unittest.TestCase):
    """一份自描述文件的插件块读法"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = Path(self._tmp.name) / "profile.json"

    def _write(self, text: str) -> None:
        """造一份自描述文件"""
        self.state.write_text(text, encoding="utf-8")

    def test_absent_state_reads_none(self) -> None:
        """文件不在与没有插件块都按从没保存过处理，读回的不是空集"""
        for text in (None, '{"token": "abc"}'):
            with self.subTest(text=text):
                if text is None:
                    self.state.unlink(missing_ok=True)
                else:
                    self._write(text)

                self.assertIsNone(load_instance_enabled(self.state, StateKeys.ENABLED))

    def test_missing_key_reads_empty_set(self) -> None:
        """块里没启用那一键时读回空集，与没有这一块是两种盘面"""
        self._write('{"plugins": {"catalog": "dig"}}')

        self.assertEqual(
            load_instance_enabled(self.state, StateKeys.ENABLED), frozenset()
        )

    def test_broken_file_reads_none(self) -> None:
        """语法坏的文件读不出，按从没保存过处理"""
        self._write('{"plugins": ')

        self.assertIsNone(load_instance_enabled(self.state, StateKeys.ENABLED))

    def test_names_are_kept_as_text(self) -> None:
        """名单成员一律收成文本，数字与串写成同一种时算同一只插件"""
        self._write('{"plugins": {"enabled": ["help", 3]}}')

        self.assertEqual(
            load_instance_enabled(self.state, StateKeys.ENABLED),
            frozenset({"help", "3"}),
        )

    def test_catalog_absent_variants_read_empty(self) -> None:
        """指纹缺键、文件坏与文件不在都读成空串"""
        for text in (None, '{"plugins": {}}', '{"plugins": '):
            with self.subTest(text=text):
                if text is None:
                    self.state.unlink(missing_ok=True)
                else:
                    self._write(text)

                self.assertEqual(
                    load_instance_catalog(self.state, StateKeys.CATALOG), ""
                )

    def test_catalog_reads_the_written_value(self) -> None:
        """盘上写了指纹即原样读出"""
        self._write('{"plugins": {"catalog": "abc123"}}')

        self.assertEqual(load_instance_catalog(self.state, StateKeys.CATALOG), "abc123")

    def test_save_keeps_other_fields(self) -> None:
        """写状态只替换插件块，凭证与备注名原样保留"""
        self._write(json.dumps({"token": "abc", "remark": "小号"}))

        save_state(self.state, ["webshot"], "dig")

        data = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(data["token"], "abc")
        self.assertEqual(data["remark"], "小号")
        self.assertEqual(data["plugins"]["enabled"], ["webshot"])
        self.assertEqual(data["plugins"]["catalog"], "dig")


if __name__ == "__main__":
    unittest.main()
