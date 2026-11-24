"""结论行那一句的三种来源

- 有结论句即用它
- 没有结论句按标红字段数出句
- 结论句与字段错都没有即回落未通过提示
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from finshin_sdk.domain import ConfigPath, SourceCode  # noqa: E402
from utils.check import failure_note  # noqa: E402


def _errors(count: int) -> dict[ConfigPath, str]:
    """造 count 条字段错"""
    return {
        ConfigPath(
            source=SourceCode("plugin.AI"), section="model", key=f"key{i}"
        ): "短句"
        for i in range(count)
    }


class FailureNoteCase(unittest.TestCase):
    """结论行失败那一句"""

    def test_detail_wins(self) -> None:
        """有结论句即用它，字段数不参与"""
        self.assertEqual(failure_note("首轮全部不通", _errors(2)), "首轮全部不通")

    def test_counts_fields(self) -> None:
        """没有结论句：按标红字段数出句"""
        self.assertEqual(failure_note("", _errors(2)), "2 项配置异常")

    def test_falls_back_without_field_errors(self) -> None:
        """结论句与字段错都没有：回落未通过提示"""
        self.assertEqual(failure_note("", {}), "来源检测未通过")


if __name__ == "__main__":
    unittest.main()
