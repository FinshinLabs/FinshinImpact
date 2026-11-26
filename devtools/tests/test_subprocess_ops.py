"""装库子进程执行管线的单元测试

- 依赖无解整段英文不上屏，末尾换成一条可操作提示，原始行仍全量落日志
- 无解与镜像源无关不再换源，普通失败仍轮完全部源
"""

import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from services.env_setup import subprocess_ops  # noqa: E402
from skin.messages import PluginMessage  # noqa: E402

_UV_OUTPUT = [
    "error: No solution found when resolving dependencies:",
    "  cause: Because demo requires foo>=2.0",
    "         And because bar==1.0 is pinned",
    "Resolved 0 packages in 12ms",
]
_INDEXES = ("https://one.example/simple", "https://two.example/simple")


class TestRunProcess(unittest.TestCase):
    """子进程输出收敛"""

    def test_no_solution_hides_english_block(self) -> None:
        """无解整段不上屏，末尾只留一条可操作提示，原始行仍全量落日志"""
        process = SimpleNamespace(stdout=iter(_UV_OUTPUT), wait=lambda: 1)
        progress: list[str] = []
        logged: list[str] = []

        with (
            patch.object(subprocess_ops, "popen_hidden", return_value=process),
            patch.object(subprocess_ops, "log_ops", side_effect=logged.extend),
        ):
            code = subprocess_ops.run_process(["uv", "pip", "install"], progress.append)

        self.assertEqual(code, 1)
        self.assertEqual(
            progress, ["Resolved 0 packages in 12ms", PluginMessage.RESOLVE_FAIL]
        )
        self.assertEqual(logged, _UV_OUTPUT)


class TestIndexRetry(unittest.TestCase):
    """换源序列"""

    def setUp(self) -> None:
        self.calls: list[str] = []

    def test_no_solution_stops_switching(self) -> None:
        """判定无解后直接返回，不再换源"""

        def fake(
            args: list[str],
            index: str,
            on_line: Callable[[str], None] | None = None,
        ) -> int:
            self.calls.append(index)
            for line in ("Resolved 0 packages in 12ms", PluginMessage.RESOLVE_FAIL):
                assert on_line is not None
                on_line(line)
            return 1

        with (
            patch.object(subprocess_ops, "UV_INDEX_URLS", _INDEXES),
            patch.object(subprocess_ops, "run_uv_once", side_effect=fake),
        ):
            code = subprocess_ops.with_index_retry(["install"], lambda line: None)

        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [_INDEXES[0]])

    def test_plain_failure_uses_all_sources(self) -> None:
        """普通失败不发识别串，按序列轮完全部源"""

        def fake(
            args: list[str],
            index: str,
            on_line: Callable[[str], None] | None = None,
        ) -> int:
            self.calls.append(index)
            return 1

        with (
            patch.object(subprocess_ops, "UV_INDEX_URLS", _INDEXES),
            patch.object(subprocess_ops, "run_uv_once", side_effect=fake),
        ):
            code = subprocess_ops.with_index_retry(["install"], lambda line: None)

        self.assertEqual(code, 1)
        self.assertEqual(self.calls, list(_INDEXES))
