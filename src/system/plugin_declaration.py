"""插件代码声明与项目声明读取"""

import ast
import builtins
import traceback
from pathlib import Path
from typing import NoReturn

from finshin_sdk import PROJECT_MANIFEST_FILE, SDK_DISTRIBUTION, SDK_VERSION
from finshin_sdk.domain import (
    PLUGIN_NAME_PREFIX,
    CommandHelp,
    CommandRole,
    FlagHelp,
    PluginDeclaration,
    PluginFileName,
    SectionHelp,
    is_flag_name,
)
from finshin_sdk.dto import PluginManifestDTO

from .distributions import requires_of
from .toml_read import read_toml
from .tool_settings import declared_dependencies
from .versions import requires_met


class PluginDeclarationError(ValueError):
    """插件声明读不出或形状不合法"""


class PluginSdkError(PluginDeclarationError):
    """插件声明的接口包区间不满足"""


def read_plugin_manifest(
    plugin_dir: Path, dir_name: str, pkg: str, *, bundled: bool
) -> PluginManifestDTO:
    """读取插件加载记录

    - 缺文件、形状错误或接口包区间不满足即拒收
    """
    declaration = _read_code_declaration(plugin_dir)
    name, deps = _project_identity(plugin_dir, dir_name, bundled=bundled)
    if not bundled:
        required = requires_of(deps, SDK_DISTRIBUTION)
        if not required:
            raise PluginSdkError(f"插件 {name} 未声明 {SDK_DISTRIBUTION} 区间，不加载")
        if requires_met(SDK_VERSION, required) is not True:
            raise PluginSdkError(
                f"插件 {name} 要求 {SDK_DISTRIBUTION} {required}，"
                f"本机 {SDK_VERSION}，不加载"
            )
    return PluginManifestDTO(
        name=name,
        module=f"{pkg}.{dir_name}",
        deps=deps,
        declaration=declaration,
    )


def _project_identity(
    plugin_dir: Path, dir_name: str, *, bundled: bool
) -> tuple[str, tuple[str, ...]]:
    """取插件名与依赖表"""
    if bundled:
        return dir_name, ()

    project_path = plugin_dir / PROJECT_MANIFEST_FILE
    data = read_toml(project_path)
    project = data.get("project") if data else None
    if not isinstance(project, dict):
        raise PluginDeclarationError(f"{project_path}:1: 缺 [project] 段")
    if project.get("name") != f"{PLUGIN_NAME_PREFIX}{dir_name}":
        raise PluginDeclarationError(
            f"{project_path}:1: name 必须是 {PLUGIN_NAME_PREFIX}{dir_name}"
        )
    deps = declared_dependencies(project_path)
    if deps is None:
        raise PluginDeclarationError(f"{project_path}:1: dependencies 形状不合法")
    return dir_name, deps


def _read_code_declaration(plugin_dir: Path) -> PluginDeclaration:
    """读取并执行同目录的代码声明"""
    path = plugin_dir / PluginFileName.DECLARATION
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PluginDeclarationError(f"{path}:1: 读不出声明文件") from error
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        raise PluginDeclarationError(
            f"{path}:{error.lineno or 1}: {error.msg}"
        ) from error

    _check_tree(tree, path)
    namespace: dict[str, object] = {
        "__builtins__": {"__import__": _sdk_import},
        "__name__": "_finshin_plugin_declaration",
    }
    try:
        exec(compile(tree, str(path), "exec"), namespace)
    except Exception as error:
        line = _error_line(error, path)
        raise PluginDeclarationError(f"{path}:{line}: {error}") from error

    declaration = namespace.get("DECLARATION")
    if not isinstance(declaration, PluginDeclaration):
        raise PluginDeclarationError(f"{path}:1: DECLARATION 形状不合法")
    _check_declaration(declaration, path)
    return declaration


def _sdk_import(
    name: str,
    globals: dict[str, object] | None = None,
    locals: dict[str, object] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> object:
    """只放行接口包及其子模块的导入"""
    if level or not (name == "finshin_sdk" or name.startswith("finshin_sdk.")):
        raise PluginDeclarationError(f"声明只许导入 finshin_sdk：{name}")
    return builtins.__import__(name, globals, locals, fromlist, level)


def _check_tree(tree: ast.Module, path: Path) -> None:
    """核声明文件的语句形状与可调用来源"""
    allowed: set[str] = set()
    assigned: set[str] = set()
    top_imports: set[ast.AST] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_imports.add(node)
            for alias in node.names:
                if not _sdk_module(alias.name):
                    _fail(path, node, "只许导入 finshin_sdk")
                allowed.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            top_imports.add(node)
            if node.level or not _sdk_module(node.module or ""):
                _fail(path, node, "只许导入 finshin_sdk")
            allowed.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                if not isinstance(target, ast.Name) or target.id.startswith("_"):
                    _fail(path, target, "赋值目标只许普通名字")
            assigned.update(
                target.id for target in targets if isinstance(target, ast.Name)
            )
            value = node.value
            if value is not None:
                _check_expr(value, path, allowed, assigned)
        elif isinstance(node, ast.FunctionDef):
            if node.name.startswith("_"):
                _fail(path, node, "函数名不许以下划线开头")
            allowed.add(node.name)
            for default in (*node.args.defaults, *node.args.kw_defaults):
                if default is not None:
                    _check_expr(default, path, allowed, assigned)
            for decorator in node.decorator_list:
                _check_expr(decorator, path, allowed, assigned)
        elif (
            node is tree.body[0]
            and isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue
        else:
            _fail(path, node, "顶层只许 finshin_sdk 导入、赋值与 def")

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node not in top_imports:
            _fail(path, node, "只许在顶层导入 finshin_sdk")
        if isinstance(node, ast.ClassDef):
            _fail(path, node, "声明文件不定义类")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            _fail(path, node, "不许访问下划线名字")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            _fail(path, node, "不许访问下划线属性")
        if isinstance(node, ast.Call):
            _check_call(node, path, allowed)


def _check_expr(
    node: ast.expr, path: Path, allowed: set[str], assigned: set[str]
) -> None:
    """核默认值与装饰器里的表达式"""
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id.startswith("_"):
            _fail(path, child, "不许访问下划线名字")
        if (
            isinstance(child, ast.Name)
            and child.id not in allowed
            and child.id not in assigned
        ):
            _fail(path, child, f"不许访问 {child.id}")
        if isinstance(child, ast.Attribute) and child.attr.startswith("_"):
            _fail(path, child, "不许访问下划线属性")
        if isinstance(child, ast.Call):
            _check_call(child, path, allowed)


def _check_call(node: ast.Call, path: Path, allowed: set[str]) -> None:
    """只许调用接口包导入件或文件内函数"""
    target = node.func
    if isinstance(target, ast.Name):
        if target.id not in allowed:
            _fail(path, target, f"不许调用 {target.id}")
        return
    if isinstance(target, ast.Attribute):
        root = target
        while isinstance(root, ast.Attribute):
            root = root.value
        if not isinstance(root, ast.Name) or root.id not in allowed:
            _fail(path, target, "属性调用只能来自 finshin_sdk 导入件")
        return
    _fail(path, target, "调用目标形状不合法")


def _sdk_module(name: str) -> bool:
    """模块名是否属于接口包"""
    return name == "finshin_sdk" or name.startswith("finshin_sdk.")


def _check_declaration(declaration: PluginDeclaration, path: Path) -> None:
    """核代码声明各层容器的真实形状"""
    if not isinstance(declaration.title, str) or not isinstance(
        declaration.summary, str
    ):
        _fail(path, None, "title 与 summary 必须是文本")
    if not isinstance(declaration.assets, tuple) or not all(
        isinstance(asset, str) for asset in declaration.assets
    ):
        _fail(path, None, "assets 必须是文本元组")
    if not isinstance(declaration.help, tuple):
        _fail(path, None, "help 必须是段元组")
    for section in declaration.help:
        if not isinstance(section, SectionHelp):
            _fail(path, None, "help 里必须是 SectionHelp")
        if not isinstance(section.section, str) or not isinstance(section.note, str):
            _fail(path, None, "段名与说明必须是文本")
        if not isinstance(section.commands, tuple):
            _fail(path, None, "commands 必须是命令元组")
        for command in section.commands:
            _check_command(command, path)


def _check_command(command: object, path: Path) -> None:
    """核一条命令及其开关"""
    if not isinstance(command, CommandHelp):
        _fail(path, None, "commands 里必须是 CommandHelp")
    if (
        not isinstance(command.cmd, str)
        or not command.cmd
        or not isinstance(command.desc, str)
        or not command.desc
    ):
        _fail(path, None, "命令名与说明必须是非空文本")
    if not isinstance(command.args, str) or not isinstance(command.role, CommandRole):
        _fail(path, None, "args 必须是文本，role 必须是 CommandRole")
    if not isinstance(command.flags, tuple):
        _fail(path, None, "flags 必须是开关元组")
    for flag in command.flags:
        if not isinstance(flag, FlagHelp):
            _fail(path, None, "flags 里必须是 FlagHelp")
        if (
            not isinstance(flag.name, str)
            or not is_flag_name(flag.name)
            or not isinstance(flag.desc, str)
            or not flag.desc
        ):
            _fail(path, None, "开关名或说明不合法")
        default = flag.default
        if default is not None and (
            isinstance(default, bool)
            or not isinstance(default, (int, float, str))
            or default == ""
        ):
            _fail(path, None, "开关默认值只许非空文本、整数或小数")


def _error_line(error: Exception, path: Path) -> int:
    """取声明文件里离出错点最近的一行"""
    frames = traceback.extract_tb(error.__traceback__)
    for frame in reversed(frames):
        if Path(frame.filename) == path:
            return frame.lineno or 1
    return 1


def _fail(path: Path, node: ast.AST | None, message: str) -> NoReturn:
    """带文件与行号报声明错误"""
    line = getattr(node, "lineno", 1)
    raise PluginDeclarationError(f"{path}:{line}: {message}")
