"""构建前工作树与版本 tag 核对用例

- 工作树干净且 HEAD 树与同名 tag 的树相同时放行
- 已跟踪文件有未提交改动时原样报出并中止
- 目标 tag 不存在时中止并提示补 tag
"""

import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packaging"))

import pack_release  # noqa: E402

_VERSION = "1.2.3"


class BuildTreeGuardCase(unittest.TestCase):
    """临时仓里的构建前核对"""

    def setUp(self) -> None:
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        (self.root / "pyproject.toml").write_text(
            f'[project]\nversion = "{_VERSION}"\n', encoding="utf-8"
        )
        self.tracked = self.root / "tracked.py"
        self.tracked.write_text("VALUE = 1\n", encoding="utf-8")
        self._git("init")
        self._git("config", "user.name", "Build Test")
        self._git("config", "user.email", "build-test@example.invalid")
        self._git("add", ".")
        self._git("commit", "-m", "initial")

    def _git(self, *args: str) -> str:
        done = subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    def test_clean_tree_matches_tag(self) -> None:
        self._git("tag", f"v{_VERSION}")
        output = io.StringIO()
        with redirect_stdout(output):
            pack_release.refuse_tree_tag_mismatch(self.root)
        self.assertIn(f"v{_VERSION}", output.getvalue())
        self.assertIn("核对通过", output.getvalue())

    def test_dirty_tracked_file_stops_build(self) -> None:
        self._git("tag", f"v{_VERSION}")
        self.tracked.write_text("VALUE = 2\n", encoding="utf-8")
        output = io.StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as ctx:
            pack_release.refuse_tree_tag_mismatch(self.root)
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(output.getvalue(), " M tracked.py\n")

    def test_missing_tag_stops_build(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            pack_release.refuse_tree_tag_mismatch(self.root)
        self.assertIn(f"v{_VERSION}", str(ctx.exception))
        self.assertIn("先 fetch 或先打 tag", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
