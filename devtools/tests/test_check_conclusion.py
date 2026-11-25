"""结论行那一句与行上详情的显示

- 有结论句即用它
- 没有结论句按标红字段数出句
- 结论句与字段错都没有即回落未通过提示
- 网页正文洗成纯文字，其余正文原样返回
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from finshin_sdk.domain.config import ConfigPath  # noqa: E402
from finshin_sdk.domain.ids import SourceCode  # noqa: E402
from skin.messages import CheckMessage  # noqa: E402
from utils.check import display_note, failure_note  # noqa: E402

_GATEWAY_PAGE = """<!DOCTYPE html>
<html>
<head>
<style>body { color: #f00; }</style>
<script>window.alert("boom")</script>
</head>
<body>
<h1>502 Bad Gateway</h1>
<p>nginx</p>
</body>
</html>"""

_EMPTY_PAGE = (
    "<html><head><style>p { margin: 0; }</style></head>"
    "<body><script>window.alert(1)</script></body></html>"
)


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


class DisplayNoteCase(unittest.TestCase):
    """行上详情的显示"""

    def test_web_page_keeps_visible_text(self) -> None:
        """整段网页只留可见文字，块级标签分行"""
        self.assertEqual(display_note(_GATEWAY_PAGE), "502 Bad Gateway\nnginx")

    def test_prefixed_page_keeps_status(self) -> None:
        """带状态码前缀的网页同样洗，前缀保留"""
        self.assertEqual(
            display_note("HTTP 502 " + _GATEWAY_PAGE),
            "HTTP 502\n502 Bad Gateway\nnginx",
        )

    def test_title_not_shown(self) -> None:
        """head 里的标题不进正文"""
        raw = (
            "<html><head><title>Error response</title></head>"
            "<body><h1>Error response</h1></body></html>"
        )
        self.assertEqual(display_note(raw), "Error response")

    def test_unclosed_head_still_reads_body(self) -> None:
        """缺 </head> 的残页仍抽到正文"""
        raw = "<html><head><title>x</title><body><p>502 Bad Gateway</p></body></html>"
        self.assertEqual(display_note(raw), "502 Bad Gateway")

    def test_prefixed_json_stays(self) -> None:
        """带状态码前缀的非网页正文原样返回"""
        raw = 'HTTP 400 {"error": "invalid_api_key"}'
        self.assertEqual(display_note(raw), raw)

    def test_json_stays(self) -> None:
        """JSON 错误正文原样返回"""
        raw = '{"error": "invalid_api_key"}'
        self.assertEqual(display_note(raw), raw)

    def test_sentence_stays(self) -> None:
        """普通短句原样返回"""
        self.assertEqual(display_note("地址或密钥不对"), "地址或密钥不对")

    def test_markup_only_falls_back(self) -> None:
        """纯标记页洗不出文字时给固定提示"""
        self.assertEqual(display_note(_EMPTY_PAGE), CheckMessage.WEB_PAGE_EMPTY)

    def test_long_text_kept_whole(self) -> None:
        """可见文字再长也不截断，靠检查窗滚动"""
        raw = "<html><body><p>" + "字" * 250 + "</p></body></html>"
        self.assertEqual(display_note(raw), "字" * 250)


if __name__ == "__main__":
    unittest.main()
