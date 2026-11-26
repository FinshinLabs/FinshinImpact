"""命名与门面导出分节检查

- 被其他模块导入的符号禁 `_` 前缀，无任何消费者建议加
- 私有模块不得替公开符号当导入路径，消费方应改从来源模块直连
- 模块级别名与函数、类同进候选集，样式归属见 _s5c_constants
- 消费者只算 src 侧调用，devtools 直连内部实现不属业务消费，其引用不给公共名转正
- 门面出口细则委托 _s5f_facade_exports
- 模块级常量细则委托 _s5c_constants
- 命名风格细则委托 _s5b_naming_style
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from ._common import Finding, ImportGraph
from ._s5b_naming_style import check_style
from ._s5c_constants import check_constants, is_type_constructor, owns_style
from ._s5f_facade_exports import check as check_facade_exports

if TYPE_CHECKING:
    from ._common import FileData


def check(files: list[FileData], graph: ImportGraph) -> list[Finding]:
    """扫描命名与门面导出违规"""
    findings: list[Finding] = []
    by_module = {f.module: f for f in files if f.module}
    dynamic = _getattr_names(files)
    findings.extend(check_facade_exports(files, graph))
    findings.extend(_check_symbol_prefix(files, graph, by_module, dynamic))
    findings.extend(_check_private_reexport(files, graph))
    for file in files:
        if file.parse_error:
            continue
        findings.extend(check_constants(file, graph, dynamic))
    findings.extend(check_style(files))
    return findings


def _getattr_names(files: list[FileData]) -> set[str]:
    """全树内 getattr 第二参数字面量，动态加载消费方对静态图不可见"""
    names: set[str] = set()
    for file in files:
        if file.parse_error:
            continue
        for node in ast.walk(file.tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "getattr" or len(node.args) < 2:
                continue
            second = node.args[1]
            if isinstance(second, ast.Constant) and isinstance(second.value, str):
                names.add(second.value)
    return names


def _check_symbol_prefix(
    files: list[FileData],
    graph: ImportGraph,
    by_module: dict[str, FileData],
    dynamic: set[str],
) -> list[Finding]:
    """符号私有性一致检查"""
    findings: list[Finding] = []
    consumed: dict[str, dict[str, set[str]]] = {}
    for target, consumers in graph.consumers.items():
        target_devtools = target in graph.devtools_modules
        merged: dict[str, set[str]] = {}
        for consumer, symbols in consumers.items():
            if consumer == target:
                continue
            if consumer in graph.devtools_modules and not target_devtools:
                continue
            for symbol in symbols:
                if symbol and symbol != "*":
                    merged.setdefault(symbol, set()).add(consumer)
        consumed[target] = merged
    for file in files:
        if file.parse_error or not file.module:
            continue
        defs = _def_defs(file)
        usage = consumed.get(file.module, {})
        entry_names = _main_entry_names(file)
        for name, line in sorted(defs.items(), key=lambda kv: kv[1]):
            if name.startswith("__"):
                continue
            if name in entry_names:
                continue
            users = usage.get(name, set())
            if name.startswith("_"):
                if users:
                    joined = ", ".join(sorted(users)[:3])
                    findings.append(
                        _f(
                            file,
                            line,
                            f"被其他模块导入的符号 `{name}` 带 `_` 前缀（{joined}）",
                            hard=True,
                        ),
                    )
            elif not users:
                if (
                    name in dynamic
                    or _has_registration_decorator(file, name)
                    or _is_plugin_entry(file, name)
                ):
                    continue
                findings.append(
                    _f(
                        file,
                        line,
                        f"符号 `{name}` 无任何消费者，应加 `_` 前缀",
                        hard=False,
                    ),
                )
    return findings


def _check_private_reexport(files: list[FileData], graph: ImportGraph) -> list[Finding]:
    """私有模块不得替公开符号当导入路径"""
    findings: list[Finding] = []
    for file in files:
        if file.parse_error or file.is_init or not file.stem.startswith("_"):
            continue
        forwarded = _imported_names(file)
        for consumer, symbols in sorted(graph.consumers.get(file.module, {}).items()):
            if consumer == file.module:
                continue
            for symbol in sorted(symbols & forwarded.keys()):
                if symbol.startswith("_"):
                    continue
                findings.append(
                    _f(
                        file,
                        forwarded[symbol],
                        f"私有模块转发公开符号 `{symbol}`（{consumer} 经本模块取用），"
                        "应改从来源模块直连",
                        hard=True,
                    ),
                )
    return findings


def _imported_names(file: FileData) -> dict[str, int]:
    """模块级 from 导入进来的名字到行号"""
    return {
        alias.asname or alias.name: node.lineno
        for node in file.tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def _is_plugin_entry(file: FileData, name: str) -> bool:
    """插件入口类由加载器按继承关系在模块里发现，属动态消费方"""
    bases = [
        base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
        for node in file.tree.body
        if isinstance(node, ast.ClassDef) and node.name == name
        for base in node.bases
    ]
    return "BasePlugin" in bases


def _has_registration_decorator(file: FileData, name: str) -> bool:
    """定义带注册型装饰器时，装饰器即运行期消费方"""
    for node in file.tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name != name:
            continue
        return any(
            isinstance(decorator, ast.Call) and bool(decorator.args)
            for decorator in node.decorator_list
        )
    return False


def _def_defs(file: FileData) -> dict[str, int]:
    """模块级函数、类与别名的名字到行号"""
    defs = {
        node.name: node.lineno
        for node in file.tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    }
    defs.update(_alias_defs(file))
    return defs


def _alias_defs(file: FileData) -> dict[str, int]:
    """模块级别名的名字到行号

    - 大写与小写蛇形两档由 _s5c_constants 认领，这里只收大写开头的别名
    - 右侧是类型构造调用的不收，标识类型集中定义处按设计公开
    """
    defs: dict[str, int] = {}
    for node in file.tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if value is None or is_type_constructor(value):
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if name.startswith("_") or not name[0].isupper() or owns_style(name):
                continue
            defs.setdefault(name, node.lineno)
    return defs


def _main_entry_names(file: FileData) -> set[str]:
    """`if __name__ == "__main__"` 块内直接调用的函数名"""
    names: set[str] = set()
    for node in file.tree.body:
        if not (isinstance(node, ast.If) and _is_name_main(node.test)):
            continue
        for call in ast.walk(node):
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                names.add(call.func.id)
    return names


def _is_name_main(test: ast.expr) -> bool:
    """判断 if 测试是否为 `__name__ == "__main__"`"""
    return (
        isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
    )


def _f(file: FileData, line: int, message: str, hard: bool) -> Finding:
    """构造本分节违规条目"""
    return Finding("命名与门面导出", file.rel, line, message, hard)
