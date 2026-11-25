"""旧配置迁移测试

- 裸段按对照表搬进来源块，键名与值不改
- core.data 搬进 plugin.AI.data，新位置已有值为准
- 新段已有键时旧值不采用
- 已是来源块的配置不写盘
- 旧插件状态并进实例自描述文件，旧文件改名留底
- 新位置已有值或读不出时不动旧文件
- 迁移目录里只许执行器、包入口与四位编号的脚本
"""

import json
import re
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.migrations import run_all  # noqa: E402
from system.migrations._0001_old_layout import apply, matches  # noqa: E402
from system.migrations._runner import MigrationInstance  # noqa: E402

_ROOT = Path("tg.000000")
_MIGRATIONS_DIR = (
    Path(__file__).resolve().parent.parent.parent / "src/system/migrations"
)
_INFRA_NAMES = {"__init__.py", "_runner.py", "_toml.py"}
_SCRIPT_NAME = re.compile(r"_(\d{4})_[a-z0-9_]+")


def _instance(document: dict[str, object]) -> MigrationInstance:
    """把一份配置表挂到固定实例目录上"""
    return MigrationInstance(root=_ROOT, document=document)


_OLD = """[proxy]
proxy_mode = "auto"

[model]
api_key = "sk-test"

[data]
record_keep = 30.0
waiting = 4.0
"""

_NEW = """[[source]]
id = "plugin.AI"

[source.model]
api_key = "sk-new"
"""

_CORE_DATA = """[[source]]
id = "core"

[source.data]
record_keep = 12.0
waiting = 2.0
"""

_AI_DATA = """[[source]]
id = "plugin.AI"

[source.data]
record_keep = 99.0
"""


class TestBareSections(unittest.TestCase):
    """裸段搬进来源块的条件与结果"""

    def test_moves_bare_sections(self) -> None:
        """旧写法搬成两类来源，值跟着走"""
        document = tomllib.loads(_OLD)

        self.assertTrue(matches(_instance(document)))
        changed, notes = apply(_instance(document))
        self.assertTrue(changed)

        self.assertNotIn("proxy", document)
        self.assertNotIn("model", document)
        self.assertNotIn("data", document)
        blocks = {block["id"]: block for block in document["source"]}
        self.assertEqual(sorted(blocks), ["adapter.tg", "plugin.AI"])
        self.assertEqual(blocks["plugin.AI"]["model"]["api_key"], "sk-test")
        self.assertEqual(
            blocks["plugin.AI"]["data"], {"record_keep": 30.0, "waiting": 4.0}
        )
        self.assertTrue(any("取旧值" in line for line in notes))

    def test_moves_core_data_to_ai(self) -> None:
        """dev8 的 core.data 搬进 AI 数据段，旧来源块撤掉"""
        document = tomllib.loads(_CORE_DATA)

        self.assertTrue(matches(_instance(document)))
        changed, notes = apply(_instance(document))
        self.assertTrue(changed)

        self.assertEqual([block["id"] for block in document["source"]], ["plugin.AI"])
        self.assertEqual(
            document["source"][0]["data"], {"record_keep": 12.0, "waiting": 2.0}
        )
        self.assertTrue(any("core.data -> plugin.AI.data" in line for line in notes))

    def test_ai_data_wins_over_both_legacy_shapes(self) -> None:
        """AI 新值先保留，core.data 次之，裸 data 只补缺"""
        document = tomllib.loads(_OLD + _CORE_DATA + _AI_DATA)

        changed, notes = apply(_instance(document))
        self.assertTrue(changed)

        blocks = {block["id"]: block for block in document["source"]}
        self.assertNotIn("core", blocks)
        self.assertEqual(
            blocks["plugin.AI"]["data"], {"record_keep": 99.0, "waiting": 2.0}
        )
        self.assertTrue(any("旧值不采用" in line for line in notes))

    def test_existing_value_wins(self) -> None:
        """新段已有的键保留新值"""
        document = tomllib.loads(_OLD + _NEW)

        changed, notes = apply(_instance(document))
        self.assertTrue(changed)

        blocks = {block["id"]: block for block in document["source"]}
        self.assertEqual(blocks["plugin.AI"]["model"]["api_key"], "sk-new")
        self.assertTrue(any("旧值不采用" in line for line in notes))

    def test_new_shape_not_matched(self) -> None:
        """已是当前来源块的配置不命中"""
        self.assertFalse(matches(_instance(tomllib.loads(_NEW))))
        self.assertFalse(matches(_instance(tomllib.loads(_AI_DATA))))


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
                ["adapter.tg", "plugin.AI"],
            )
            self.assertTrue((instance / "config.toml.bak").is_file())
            self.assertEqual(run_all(Path(tmp), report=lambda _: None), 0)

    def test_core_data_writes_once_with_backup(self) -> None:
        """core.data 写回一次并留备份，再跑不动"""
        with tempfile.TemporaryDirectory() as tmp:
            instance = Path(tmp) / "tg.000001"
            instance.mkdir()
            config = instance / "config.toml"
            config.write_text(_CORE_DATA, encoding="utf-8")

            self.assertEqual(run_all(Path(tmp), report=lambda _: None), 1)
            migrated = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(
                [block["id"] for block in migrated["source"]], ["plugin.AI"]
            )
            self.assertEqual(
                migrated["source"][0]["data"],
                {"record_keep": 12.0, "waiting": 2.0},
            )
            self.assertEqual(
                (instance / "config.toml.bak").read_text(encoding="utf-8"),
                _CORE_DATA,
            )
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

    def test_config_and_state_in_one_pass(self) -> None:
        """配置与旧插件状态同一遍处理，配置只写回一次"""
        with tempfile.TemporaryDirectory() as tmp:
            instance = Path(tmp) / "tg.000001"
            instance.mkdir()
            config = instance / "config.toml"
            config.write_text(_OLD, encoding="utf-8")
            (instance / "plugins.toml").write_text(_OLD_STATE, encoding="utf-8")
            (instance / "profile.json").write_text(_PROFILE, encoding="utf-8")

            lines: list[str] = []
            self.assertEqual(run_all(Path(tmp), report=lines.append), 1)

            migrated = tomllib.loads(config.read_text(encoding="utf-8"))
            self.assertEqual(
                [block["id"] for block in migrated["source"]][:2],
                ["adapter.tg", "plugin.AI"],
            )
            self.assertFalse((instance / "plugins.toml").exists())
            self.assertTrue(any("插件状态" in line for line in lines))
            self.assertEqual(
                (instance / "config.toml.bak").read_text(encoding="utf-8"), _OLD
            )


_OLD_STATE = 'enabled = ["webshot"]\ncatalog = "dig"\n'
_PROFILE = '{"token": "abc", "remark": "小号"}'
_ENABLED_BLOCK = '{"plugins": {"enabled": ["help"], "catalog": "old"}}'


class TestPluginState(unittest.TestCase):
    """旧插件状态并进自描述文件"""

    def _instance(self, tmp: str) -> Path:
        instance = Path(tmp) / "tg.000001"
        instance.mkdir()
        return instance

    def test_moves_state_and_retires_file(self) -> None:
        """启用集与指纹搬进状态块，凭证照留，旧文件改名留底"""
        with tempfile.TemporaryDirectory() as tmp:
            instance = self._instance(tmp)
            (instance / "plugins.toml").write_text(_OLD_STATE, encoding="utf-8")
            profile = instance / "profile.json"
            profile.write_text(_PROFILE, encoding="utf-8")

            self.assertEqual(run_all(Path(tmp), report=lambda _: None), 1)

            data = json.loads(profile.read_text(encoding="utf-8"))
            self.assertEqual(data["token"], "abc")
            self.assertEqual(data["remark"], "小号")
            self.assertEqual(data["plugins"]["enabled"], ["webshot"])
            self.assertEqual(data["plugins"]["catalog"], "dig")
            self.assertFalse((instance / "plugins.toml").exists())
            self.assertTrue((instance / "plugins.toml.bak").is_file())
            self.assertEqual(
                (instance / "profile.json.bak").read_text(encoding="utf-8"), _PROFILE
            )
            self.assertEqual(run_all(Path(tmp), report=lambda _: None), 0)

    def test_existing_block_wins(self) -> None:
        """新位置已有状态块时只把旧文件改名，块里的值不动"""
        with tempfile.TemporaryDirectory() as tmp:
            instance = self._instance(tmp)
            (instance / "plugins.toml").write_text(_OLD_STATE, encoding="utf-8")
            profile = instance / "profile.json"
            profile.write_text(_ENABLED_BLOCK, encoding="utf-8")

            lines: list[str] = []
            self.assertEqual(run_all(Path(tmp), report=lines.append), 1)

            data = json.loads(profile.read_text(encoding="utf-8"))
            self.assertEqual(data["plugins"]["enabled"], ["help"])
            self.assertFalse((instance / "plugins.toml").exists())
            self.assertTrue(any("新位置已有值" in line for line in lines))

    def test_broken_old_file_untouched(self) -> None:
        """旧文件读不出时两边都不动"""
        with tempfile.TemporaryDirectory() as tmp:
            instance = self._instance(tmp)
            (instance / "plugins.toml").write_text("enabled = [", encoding="utf-8")
            profile = instance / "profile.json"
            profile.write_text(_PROFILE, encoding="utf-8")

            self.assertEqual(run_all(Path(tmp), report=lambda _: None), 0)
            self.assertTrue((instance / "plugins.toml").is_file())
            self.assertFalse((instance / "profile.json.bak").exists())
            self.assertEqual(profile.read_text(encoding="utf-8"), _PROFILE)

    def test_missing_profile_keeps_old_file(self) -> None:
        """自描述文件读不出时不动旧文件"""
        with tempfile.TemporaryDirectory() as tmp:
            instance = self._instance(tmp)
            (instance / "plugins.toml").write_text(_OLD_STATE, encoding="utf-8")

            lines: list[str] = []
            self.assertEqual(run_all(Path(tmp), report=lines.append), 0)
            self.assertTrue((instance / "plugins.toml").is_file())
            self.assertTrue(any("读不出" in line for line in lines))


class TestScriptNames(unittest.TestCase):
    """迁移脚本文件名形状

    - 只许执行器、包入口与四位编号的脚本
    - 编号不重复，缺号不补
    """

    def test_only_numbered_scripts(self) -> None:
        """往目录扔一支没编号的脚本应当红"""
        numbered: list[str] = []
        bad: list[str] = []
        for path in _MIGRATIONS_DIR.glob("*.py"):
            if path.name in _INFRA_NAMES:
                continue
            found = _SCRIPT_NAME.fullmatch(path.stem)
            if found is None:
                bad.append(path.name)
            else:
                numbered.append(found.group(1))
        self.assertEqual(bad, [])
        self.assertEqual(len(numbered), len(set(numbered)))


if __name__ == "__main__":
    unittest.main()
