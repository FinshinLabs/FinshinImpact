"""门面出口检查

- 仅被自家包门面导入的子模块应带 `_` 前缀
- `_` 前缀模块被包外直接导入提示转正
- 惰性门面表不得把符号指向公开模块，消费方直连该模块
- 包外不得经门面取用同包公开子模块代发的符号
- 门面不声明 `__all__`，导入即出口
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from ._common import Finding, ImportGraph

if TYPE_CHECKING:
    from ._common import FileData


def check(files: list[FileData], graph: ImportGraph) -> list[Finding]:
    """扫描包门面的出口形状"""
    findings: list[Finding] = []
    findings.extend(_check_module_prefix(files, graph))
    findings.extend(_check_lazy_targets(files))
    findings.extend(_check_public_forwarding(files, graph))
    findings.extend(_check_all_declared(files))
    return findings


def _outside_consumers(graph: ImportGraph, target: str) -> set[str]:
    """包外消费者集合，工具侧直连的不计

    - devtools 消费方不计入 src 符号的转正，但 devtools 自家树互用是真消费者
    """
    package = target.rpartition(".")[0]
    target_devtools = target in graph.devtools_modules
    consumers = graph.consumers.get(target, {})
    result: set[str] = set()
    for module in consumers:
        if module in {target, package}:
            continue
        if module.rpartition(".")[0] == package:
            continue
        if module in graph.devtools_modules and not target_devtools:
            continue
        if _is_ancestor_package(module, package):
            continue
        result.add(module)
    return result


def _is_ancestor_package(module: str, package: str) -> bool:
    """子包模块使用父包内部模块属包内互用"""
    return bool(package) and module.startswith(f"{package}.")


def _check_module_prefix(files: list[FileData], graph: ImportGraph) -> list[Finding]:
    """子模块文件名的内外前缀规则"""
    findings: list[Finding] = []
    for file in files:
        if file.is_init or not file.module:
            continue
        consumers = graph.consumers.get(file.module, {})
        only_facade = bool(consumers) and set(consumers) == {file.package}
        if not file.stem.startswith("_") and only_facade:
            findings.append(
                _f(
                    file,
                    1,
                    f"子模块 `{file.rel}` 仅被包门面导入，按规范应加 `_` 前缀",
                    hard=False,
                ),
            )
        if file.stem.startswith("_"):
            outside = _outside_consumers(graph, file.module)
            if outside:
                joined = ", ".join(sorted(outside)[:3])
                findings.append(
                    _f(
                        file,
                        1,
                        f"内部模块 `{file.rel}` 被包外直接导入（{joined}），应转正去前缀",
                        hard=True,
                    ),
                )
    return findings


def _check_lazy_targets(files: list[FileData]) -> list[Finding]:
    """惰性门面表指向的模块须为私有模块"""
    findings: list[Finding] = []
    for file in files:
        if file.parse_error or not file.is_init:
            continue
        for name, target, line in _lazy_targets(file):
            leaf = target.rpartition(".")[2]
            if leaf and not leaf.startswith("_"):
                findings.append(
                    _f(
                        file,
                        line,
                        f"惰性门面把 `{name}` 指向公开模块 `{target}`，"
                        "消费方应直连该模块",
                        hard=True,
                    ),
                )
    return findings


def _lazy_targets(file: FileData) -> list[tuple[str, str, int]]:
    """`_SYMBOL_MODULES` 表里符号名、目标模块与行号"""
    entries: list[tuple[str, str, int]] = []
    for node in file.tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if not isinstance(value, ast.Dict):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_SYMBOL_MODULES"
            for target in targets
        ):
            continue
        for key, val in zip(value.keys, value.values, strict=True):
            name = _string_literal(key)
            target = _string_literal(val)
            if name is not None and target is not None and key is not None:
                entries.append((name, target, key.lineno))
    return entries


def _string_literal(node: ast.expr | None) -> str | None:
    """字面量字符串取值，其余回 None"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _check_public_forwarding(
    files: list[FileData], graph: ImportGraph
) -> list[Finding]:
    """包外经门面取用公开子模块符号报硬性"""
    findings: list[Finding] = []
    for file in files:
        if file.parse_error or not file.is_init:
            continue
        forwarded = _public_forwarders(file)
        for consumer, symbols in sorted(graph.consumers.get(file.module, {}).items()):
            if consumer == file.module or _is_ancestor_package(consumer, file.package):
                continue
            for name, (source, line) in sorted(forwarded.items()):
                if name in symbols:
                    findings.append(
                        _f(
                            file,
                            line,
                            f"门面代发公开子模块符号 `{name}`（{consumer} 经本模块取用），"
                            f"消费方应直连 `{source}`",
                            hard=True,
                        )
                    )
    return findings


def _public_forwarders(file: FileData) -> dict[str, tuple[str, int]]:
    """门面从同包公开子模块导入的别名到来源与行号"""
    forwarded: dict[str, tuple[str, int]] = {}
    for node in file.tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        source = _from_module(file, node)
        if source.rpartition(".")[0] != file.package:
            continue
        if source.rpartition(".")[2].startswith("_"):
            continue
        for alias in node.names:
            if alias.name != "*":
                forwarded.setdefault(alias.asname or alias.name, (source, node.lineno))
    return forwarded


def _from_module(file: FileData, node: ast.ImportFrom) -> str:
    """把门面里的相对导入折算成点分模块名"""
    if not node.level:
        return node.module or ""
    parts = file.package.split(".") if file.package else []
    up = node.level - 1
    if up > len(parts):
        return ""
    base = ".".join(parts[: len(parts) - up]) if up else file.package
    return f"{base}.{node.module}" if node.module else base


def _check_all_declared(files: list[FileData]) -> list[Finding]:
    """检查门面是否声明 `__all__`"""
    findings: list[Finding] = []
    for file in files:
        if file.parse_error or not file.is_init:
            continue
        for node in file.tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            if any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in targets
            ):
                findings.append(
                    _f(
                        file,
                        node.lineno,
                        "门面不再声明 `__all__`，导入即出口",
                        hard=True,
                    ),
                )
    return findings


def _f(file: FileData, line: int, message: str, hard: bool) -> Finding:
    """构造本分节违规条目"""
    return Finding("命名与门面导出", file.rel, line, message, hard)
