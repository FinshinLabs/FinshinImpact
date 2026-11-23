"""本体插件名册的单元测试

- 覆盖随包名单三只恒在场与档位表首末两档
- 覆盖表外插件抢随包命令名记冲突
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from finshin_sdk.domain import (  # noqa: E402
    CommandTaken,
    PluginClaim,
    PluginPriority,
)
from system.plugin_roster import (  # noqa: E402
    BUNDLED_PLUGINS,
    BUNDLED_PRIORITY_TABLE,
    is_plugin_enabled,
    resolve_claims,
)


class TestBundledRoster(unittest.TestCase):
    """随包名单与加载档位"""

    def test_bundled_plugins_include_grant(self) -> None:
        """随包名单三只，启用集为空也在场"""
        self.assertEqual(BUNDLED_PLUGINS, frozenset({"help", "grant", "AI"}))
        for name in BUNDLED_PLUGINS:
            self.assertTrue(is_plugin_enabled(name, None))

    def test_priority_table_covers_first_and_last(self) -> None:
        """档位表只留首末两档"""
        self.assertEqual(set(BUNDLED_PRIORITY_TABLE), {"help", "AI"})
        self.assertIs(BUNDLED_PRIORITY_TABLE["help"], PluginPriority.FIRST)
        self.assertIs(BUNDLED_PRIORITY_TABLE["AI"], PluginPriority.LAST)


class TestClaimResolution(unittest.TestCase):
    """命令名抢占判定"""

    def test_resolve_claims_prefers_bundled_plugin(self) -> None:
        """随包插件拿走同名命令，表外插件记冲突"""
        allowed, conflicts = resolve_claims(
            (PluginClaim("help", ("ping",)), PluginClaim("demo", ("ping",))),
            frozenset({"demo"}),
        )

        self.assertEqual(allowed, frozenset({"help"}))
        self.assertEqual(conflicts, {"demo": (CommandTaken("ping", "help"),)})


if __name__ == "__main__":
    unittest.main()
