"""旧配置迁移测试

- 裸段按对照表搬进来源块，键名与值不改
- 新段已有键时旧值不采用
- 已是来源块的配置不写盘
"""

import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.migrations import run_all  # noqa: E402
from system.migrations._0001_bare_sections import apply, matches  # noqa: E402

_OLD = """[proxy]
proxy_mode = "auto"

[model]
api_key = "sk-test"

[data]
record_keep = 30.0
"""

_NEW = """[[source]]
id = "plugin.AI"

[source.model]
api_key = "sk-new"
"""


class TestBareSections(unittest.TestCase):
    """裸段搬进来源块的条件与结果"""

    def test_moves_bare_sections(self) -> None:
        """旧写法搬成三块来源，值跟着走"""
        document = tomllib.loads(_OLD)

        self.assertTrue(matches(document))
        notes = apply(document)

        self.assertNotIn("proxy", document)
        self.assertNotIn("model", document)
        self.assertNotIn("data", document)
        blocks = {block["id"]: block for block in document["source"]}
        self.assertEqual(sorted(blocks), ["adapter.tg", "core", "plugin.AI"])
        self.assertEqual(blocks["plugin.AI"]["model"]["api_key"], "sk-test")
        self.assertTrue(any("取旧值" in line for line in notes))

    def test_existing_value_wins(self) -> None:
        """新段已有的键保留新值"""
        document = tomllib.loads(_OLD + _NEW)

        notes = apply(document)

        blocks = {block["id"]: block for block in document["source"]}
        self.assertEqual(blocks["plugin.AI"]["model"]["api_key"], "sk-new")
        self.assertTrue(any("旧值不采用" in line for line in notes))

    def test_new_shape_not_matched(self) -> None:
        """已是来源块的配置不再命中"""
        self.assertFalse(matches(tomllib.loads(_NEW)))


class TestRunner(unittest.TestCase):
    """执行器写盘与重复执行"""

    def test_writes_once_with_backup(self) -> None:
        """旧配置写回一次，留备份，再跑不动"""
        with tempfile.TemporaryDirectory() as tmp:
            instance = Path(tmp) / "tg.000001"
            instance.mkdir()
            config = instance / "config.toml"
            config.write_text(_OLD, encoding="utf-8")

            self.assertEqual(run_all(Path(tmp), report=lambda _: None), 1)
            migrated = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(
                [block["id"] for block in migrated["source"]],
                ["adapter.tg", "plugin.AI", "core"],
            )
            self.assertTrue((instance / "config.toml.bak").is_file())
            self.assertEqual(run_all(Path(tmp), report=lambda _: None), 0)

    def test_backup_keeps_first_original(self) -> None:
        """连着两次迁移不动第一份备份"""
        with tempfile.TemporaryDirectory() as tmp:
            instance = Path(tmp) / "tg.000001"
            instance.mkdir()
            config = instance / "config.toml"
            config.write_text(_OLD, encoding="utf-8")
            run_all(Path(tmp), report=lambda _: None)

            config.write_text(_OLD.replace("sk-test", "sk-second"), encoding="utf-8")
            self.assertEqual(run_all(Path(tmp), report=lambda _: None), 1)

            backup = (instance / "config.toml.bak").read_text(encoding="utf-8")
            self.assertEqual(backup, _OLD)


if __name__ == "__main__":
    unittest.main()
