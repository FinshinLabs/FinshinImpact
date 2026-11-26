"""文件骨架分节检查

- 首行必须是模块 docstring，不写路径注释
- 模块 docstring 存在且首行为定位
- 禁止区块标题注释与装饰横线
- 主入口 if __name__ 块位于文件末尾
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from ._common import Finding

if TYPE_CHECKING:
    from ._common import FileData

# 骨架废话标题词表
_SECTION_WORDS = (
    "导入",
    "全局常量",
    "常量与配置",
    "对外暴露",
    "核心业务",
    "业务逻辑",
    "主程序入口",
    "脚本直接运行",
    "主入口",
)

# 装饰符号连排达此数即判装饰线，单个减号与下划线属正常书写（`# -1`、`# _MAX_RETRIES`）
_DECORATION_MIN = 2
_DECORATION_RE = re.compile(rf"[=\-*~─—_]{{{_DECORATION_MIN},}}(?![\w])")

# 词表项容许的拼接字数，超出即视为说明句而非标题
_TITLE_SLACK = 4
_SENTENCE_RE = re.compile(r"[，。：；,.;]")


def check(files: list[FileData]) -> list[Finding]:
    """扫描文件骨架违规"""
    findings: list[Finding] = []
    for file in files:
        if file.parse_error:
            findings.append(
                _f(file, 1, f"解析失败无法检查骨架：{file.parse_error}", hard=True),
            )
            continue
        findings.extend(_check_first_line(file))
        findings.extend(_check_module_docstring(file))
        findings.extend(_check_section_titles(file))
        findings.extend(_check_main_entry(file))
    return findings


def _check_first_line(file: FileData) -> list[Finding]:
    """首行注释禁令检查"""
    first = file.lines[0].strip() if file.lines else ""
    if first.startswith("#"):
        return [
            _f(
                file,
                1,
                f"首行是注释 `{first}`，文件首行必须是模块 docstring",
                hard=True,
            )
        ]
    return []


def _check_module_docstring(file: FileData) -> list[Finding]:
    """模块 docstring 检查"""
    node = _module_docstring_node(file)
    if node is None:
        return [_f(file, 1, "缺少模块 docstring", hard=False)]
    findings: list[Finding] = []
    seen_detail = False
    for line in range(node.lineno + 1, (node.end_lineno or node.lineno) + 1):
        raw = file.lines[line - 1].strip().strip('"').strip("'").strip()
        if not raw or raw in ('"""', "'''"):
            continue
        if not seen_detail:
            seen_detail = True
        if not raw.startswith("-"):
            findings.append(
                _f(file, line, f"模块 docstring 详情行未以 `-` 起头：{raw}", hard=False)
            )
    return findings


def _module_docstring_node(file: FileData) -> ast.Constant | None:
    """取模块 docstring 字面量节点"""
    if not file.tree.body:
        return None
    first = file.tree.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return first.value
    return None


def _check_section_titles(file: FileData) -> list[Finding]:
    """区块标题注释与装饰横线"""
    findings: list[Finding] = []
    for line, text in sorted(file.comments.items()):
        if _DECORATION_RE.match(text):
            findings.append(
                _f(file, line, f"装饰横线/区块标题注释：`# {text}`", hard=True)
            )
            continue
        core = re.sub(r"[=\-─—#\s]+", "", text)
        if _is_section_title(core):
            findings.append(_f(file, line, f"区块标题注释：`# {text}`", hard=True))
    return findings


def _is_section_title(core: str) -> bool:
    """去符号后的注释文本是否属区块标题，拼合写法一并判"""
    if not core or _SENTENCE_RE.search(core):
        return False
    return any(
        word == core or (word in core and len(core) <= len(word) + _TITLE_SLACK)
        for word in _SECTION_WORDS
    )


def _check_main_entry(file: FileData) -> list[Finding]:
    """If __name__ 主入口必须在文件最底部"""
    main_nodes = [
        node
        for node in file.tree.body
        if isinstance(node, ast.If) and _is_name_main(node.test)
    ]
    if not main_nodes:
        return []
    last = main_nodes[-1]
    tail = last.end_lineno or last.lineno
    after = [n for n in file.tree.body if n.lineno > tail]
    if after:
        return [
            _f(
                file,
                after[0].lineno,
                f"主入口之后仍有代码（第 {after[0].lineno} 行 {type(after[0]).__name__}）",
                hard=False,
            ),
        ]
    return []


def _is_name_main(test: ast.expr) -> bool:
    """判断 if 测试是否为 __name__ == '__main__'"""
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
    )


def _f(file: FileData, line: int, message: str, hard: bool) -> Finding:
    """构造本分节违规条目"""
    return Finding("文件骨架", file.rel, line, message, hard)
