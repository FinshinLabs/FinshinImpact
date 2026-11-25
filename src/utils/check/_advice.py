"""检查窗的结论短句与行上详情

- 结论行失败时按结论句或标红字段数出句
- 行上详情把整段网页洗成纯文字
"""

import re
from html.parser import HTMLParser

from skin.messages import CheckMessage, DialogMessage

from ..config.models import FieldErrors

_PAGE_HEADS = ("<!doctype", "<html")
_STATUS_PREFIX = re.compile(r"^(HTTP \d{3})\s+")
_HIDDEN_TAGS = frozenset({"script", "style"})
_BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
_WHITESPACE = re.compile(r"\s+")


def failure_note(detail: str, field_errors: FieldErrors) -> str:
    """结论行失败那一句

    - 有结论句先用它，没有按标红字段数出句
    - 一个字段错都没有即回落未通过提示
    """
    if detail:
        return detail
    if field_errors:
        return CheckMessage.VERIFY_ADVICE_FAIL.format(n=len(field_errors))
    return DialogMessage.CHECK_PROBE_HEAD_FAIL


class _PageText(HTMLParser):
    """网页可见文字抽取

    - head、script 与 style 内容整段跳过
    - 块级标签断行
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_head = False
        self._hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "head":
            self._in_head = True
        elif tag == "body":
            # 缺 </head> 的残页在 body 处收尾
            self._in_head = False
        elif tag in _HIDDEN_TAGS:
            self._hidden += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._in_head = False
        elif tag in _HIDDEN_TAGS and self._hidden:
            self._hidden -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._in_head and not self._hidden:
            self.parts.append(data)


def display_note(raw: str) -> str:
    """行上显示详情

    - 网页正文只留可见文字，按段落分行，状态码独占一行
    - 洗不出文字给固定提示
    """
    text = raw.lstrip()
    status = ""
    match = _STATUS_PREFIX.match(text)
    if match:
        status = match.group(1)
        text = text[match.end() :]
    if not text.lower().startswith(_PAGE_HEADS):
        return raw
    page = _PageText()
    page.feed(text)
    page.close()
    lines: list[str] = []
    for part in "".join(page.parts).split("\n"):
        line = _WHITESPACE.sub(" ", part).strip()
        if line:
            lines.append(line)
    if not lines:
        return _with_status(status, CheckMessage.WEB_PAGE_EMPTY)
    return _with_status(status, "\n".join(lines))


def _with_status(status: str, note: str) -> str:
    """状态码独占一行"""
    return f"{status}\n{note}" if status else note
