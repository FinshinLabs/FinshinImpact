"""实例路径的平台码分支

- 导入期缺平台段直接报错
"""

import importlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from exceptions import PlatformMissingError  # noqa: E402
from system.profile_env import set_profile  # noqa: E402
from utils import paths  # noqa: E402

_MESSAGE = "没有可用的平台适配器\n请先装一个平台适配器，再重新打开本程序"


class TestPathsPlatform(unittest.TestCase):
    """实例路径取平台码"""

    def test_missing_platform_reports_no_adapter(self) -> None:
        """身份码没有平台段即报没有可用的平台适配器"""
        try:
            set_profile("nodot")
            with self.assertRaises(PlatformMissingError) as caught:
                importlib.reload(paths)
            self.assertEqual(str(caught.exception), _MESSAGE)
        finally:
            set_profile("tg.000000")
            importlib.reload(paths)


if __name__ == "__main__":
    unittest.main()
