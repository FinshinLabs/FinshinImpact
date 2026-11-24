"""插件加载记录读取器

- 扫描插件目录聚合各插件自描述加载记录
- 按实例自描述文件里的启用集算启用序列
- 外部根里名字撞上随包表的插件整份不放行
- 命令名被在场插件拿走的整只不放行
"""

import importlib.util
from pathlib import Path

from finshin_sdk.domain import PluginClaim, PluginFileName, PluginPriority
from finshin_sdk.dto import PluginManifestDTO
from system.module_mount import mount_module, mount_package
from system.plugin_declaration import (
    PluginDeclarationError,
    PluginSdkError,
    read_plugin_manifest,
)
from system.plugin_roster import (
    BUNDLED_PLUGINS,
    BUNDLED_PLUGINS_PKG,
    BUNDLED_PRIORITY_TABLE,
    INSTALLED_PLUGINS_DIR,
    INSTALLED_PLUGINS_PKG,
    is_plugin_enabled,
    resolve_claims,
)
from system.plugin_state import StateKeys, load_instance_enabled
from system.profile_env import ROOT_DIR

from ..logger import get_logger

_logger = get_logger("Plugin")

# 插件根：目录与这棵树的顶层包名
_PluginRoot = tuple[Path, str]

# 外部插件代码所在的目录名
_CODE_STEM = "src"


def _bundled_dir() -> Path | None:
    """定位随包插件包目录

    - find_spec 只定位不执行模块代码，冻结包下路径随包走
    - 定位失败返回 None，由调用方处理
    """
    spec = importlib.util.find_spec(BUNDLED_PLUGINS_PKG)
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(next(iter(spec.submodule_search_locations)))


def _installed_dir() -> Path:
    """定位外部插件挂载点"""
    return ROOT_DIR / INSTALLED_PLUGINS_DIR


def _plugins_roots() -> list[_PluginRoot]:
    """插件根清单

    - 随包在前，外部在后

    - 外部目录不存在即不进表
    """
    roots: list[_PluginRoot] = []

    bundled = _bundled_dir()
    if bundled is not None:
        roots.append((bundled, BUNDLED_PLUGINS_PKG))

    installed = _installed_dir()
    if installed.is_dir():
        mount_package(INSTALLED_PLUGINS_PKG, installed)
        roots.append((installed, INSTALLED_PLUGINS_PKG))

    return roots


def _code_dir(plugin_dir: Path) -> Path:
    """插件代码所在那一层

    - 有 src 就认它，没有就认插件目录本身
    """
    code = plugin_dir / _CODE_STEM
    return code if code.is_dir() else plugin_dir


def _load_manifests(
    plugins_path: Path, pkg: str, mount_code: bool
) -> dict[str, PluginManifestDTO]:
    """扫描插件目录聚合加载记录

    - 只认含声明文件的直接子目录
    - 按目录名升序插入，dict 保序
    - 读取失败或字段非法的插件跳过
    """
    manifests: dict[str, PluginManifestDTO] = {}

    if not plugins_path.is_dir():
        return manifests

    for path in sorted(plugins_path.iterdir()):
        manifest = _read_manifest(path, path.name, pkg)
        if manifest is not None:
            if mount_code:
                code = _code_dir(path)
                if code != path:
                    mount_module(manifest.module, code)
            manifests[manifest.name] = manifest

    return manifests


def _read_manifest(dir_path: Path, dir_name: str, pkg: str) -> PluginManifestDTO | None:
    """读取单份插件加载记录

    - 缺声明文件即跳过，不导入插件包
    - 代码声明、项目声明或接口包区间不合法即整只拒收
    """
    if not (dir_path / PluginFileName.DECLARATION).is_file():
        return None
    try:
        return read_plugin_manifest(
            dir_path, dir_name, pkg, bundled=pkg == BUNDLED_PLUGINS_PKG
        )
    except PluginSdkError as error:
        _logger.info(str(error))
    except PluginDeclarationError as error:
        _logger.debug(str(error))
    return None


def _resolve_enabled(
    manifests: dict[str, PluginManifestDTO],
    enabled: frozenset[str] | None,
) -> list[PluginManifestDTO]:
    """计算启用插件序列

    - 在场与否由 is_plugin_enabled 定，随包表里的插件恒启用
    - 档位查 BUNDLED_PRIORITY_TABLE，表外一律常规档，同档按 name 字典序
    """
    picked = [
        manifest
        for manifest in manifests.values()
        if is_plugin_enabled(manifest.name, enabled)
    ]
    return sorted(
        picked,
        key=lambda m: (
            BUNDLED_PRIORITY_TABLE.get(m.name, PluginPriority.NORMAL),
            m.name,
        ),
    )


def _declared_commands(manifest: PluginManifestDTO) -> tuple[str, ...]:
    """取代码声明里的命令名"""
    return tuple(
        command.cmd
        for section in manifest.declaration.help
        for command in section.commands
    )


def enabled_manifests(state_path: Path) -> list[PluginManifestDTO]:
    """读取启用插件的加载记录序列

    - 注册表与帮助聚合共用本函数取序列
    - 一根目录都定位不到或无声明返回空列表
    - 外部根里名字撞上随包表的插件不进序列，改名单也不放行
    - 同名插件按根的顺序取先读到的，随包压住外部
    - 命令名被在场插件拿走的整只不进序列，互抢的多只表外插件一起不作数
    """
    manifests: dict[str, PluginManifestDTO] = {}
    for dir_path, pkg in _plugins_roots():
        for name, manifest in _load_manifests(
            dir_path, pkg, pkg != BUNDLED_PLUGINS_PKG
        ).items():
            if pkg != BUNDLED_PLUGINS_PKG and name in BUNDLED_PLUGINS:
                continue
            manifests.setdefault(name, manifest)

    enabled = load_instance_enabled(state_path, StateKeys.ENABLED)
    claims = [
        PluginClaim(name=manifest.name, commands=_declared_commands(manifest))
        for manifest in manifests.values()
    ]
    allowed, _ = resolve_claims(claims, enabled)

    return [
        manifest
        for manifest in _resolve_enabled(manifests, enabled)
        if manifest.name in allowed
    ]
