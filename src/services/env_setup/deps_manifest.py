"""插件加载记录读取

- 面板与启动判定读取代码声明
- 外部插件的库取自家声明的依赖表，随包插件的库在根声明里
- 目录指纹只随名称、依赖与资源变化
"""

import importlib.util
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from finshin_sdk.domain import PluginFileName
from finshin_sdk.dto import PluginManifestDTO
from system.digest import lines_digest
from system.plugin_declaration import PluginDeclarationError, read_plugin_manifest
from system.plugin_roster import (
    BUNDLED_PLUGINS,
    BUNDLED_PLUGINS_PKG,
    INSTALLED_PLUGINS_DIR,
    INSTALLED_PLUGINS_PKG,
)
from system.plugin_state import StateKeys, load_instance_catalog, state_path_of
from system.profile_env import ROOT_DIR

# 依赖 pin 串顶层包名截断符，"playwright>=1.40" 切出 "playwright"
_PIN_SPLIT = re.compile(r"[<>=!~\[;\s]+")

# 插件根：目录与这棵树的顶层包名
_PluginRoot = tuple[Path, str]


def plugins_roots() -> list[_PluginRoot]:
    """列出插件根与各自的顶层包名

    - 随包在前外部而后
    - 外部目录不存在即不进表
    """
    roots: list[_PluginRoot] = []

    spec = importlib.util.find_spec(BUNDLED_PLUGINS_PKG)
    if spec is not None and spec.submodule_search_locations:
        roots.append(
            (Path(next(iter(spec.submodule_search_locations))), BUNDLED_PLUGINS_PKG)
        )

    installed = ROOT_DIR / INSTALLED_PLUGINS_DIR
    if installed.is_dir():
        roots.append((installed, INSTALLED_PLUGINS_PKG))

    return roots


def _scan_rows(roots: Sequence[_PluginRoot]) -> list[PluginManifestDTO]:
    """按目录顺序读取插件加载记录

    - 无声明文件、形状不合法或接口包区间不满足的子目录跳过
    - 外部插件缺项目声明或名字形状不符即跳过
    """
    rows: list[PluginManifestDTO] = []
    for plugins_path, pkg in roots:
        if not plugins_path.is_dir():
            continue

        for path in sorted(plugins_path.iterdir()):
            if not (path / PluginFileName.DECLARATION).is_file():
                continue
            try:
                rows.append(
                    read_plugin_manifest(
                        path,
                        path.name,
                        pkg,
                        bundled=pkg == BUNDLED_PLUGINS_PKG,
                    )
                )
            except PluginDeclarationError:
                continue

    return rows


def load_manifests(roots: Sequence[_PluginRoot]) -> list[PluginManifestDTO]:
    """扫描插件根目录聚合加载记录

    - 同名插件按根的顺序取先读到的，随包压住外部同名
    - 随包表里的先成一组，两组组内都按显示名的拼音序
    """
    found: dict[str, PluginManifestDTO] = {}
    for row in _scan_rows(roots):
        found.setdefault(row.name, row)

    return sorted(found.values(), key=_sort_key)


def shadowed_manifests(
    roots: Sequence[_PluginRoot],
) -> list[tuple[PluginManifestDTO, str]]:
    """读出被同名前一份顶掉的插件记录

    - 交出 (被顶掉的加载记录, 插件名) 序列
    - 同一名字只在先读到的根里算一条
    """
    claimed: set[str] = set()
    shadowed: list[tuple[PluginManifestDTO, str]] = []
    for row in _scan_rows(roots):
        if row.name in claimed:
            shadowed.append((row, row.name))
            continue
        claimed.add(row.name)

    return shadowed


def catalog_digest(manifests: list[PluginManifestDTO]) -> str:
    """计算目录指纹

    - 只摘要名称、依赖与资源
    - 行序与扫描顺序无关，同集合必同摘要
    """
    items = sorted(
        f"{manifest.name}"
        f"|{'|'.join(manifest.deps)}"
        f"|{'|'.join(manifest.declaration.assets)}"
        for manifest in manifests
    )
    return lines_digest(items)


def _sort_key(manifest: PluginManifestDTO) -> tuple[Any, ...]:
    """拼面板行序的排序键

    - 先分来源组，组内按显示名的拼音序
    - 显示名取标题，没填标题时退化成目录名
    - 拼音相同再比显示名整串，仍相同比目录名
    """
    display = manifest.declaration.title or manifest.name
    return (
        manifest.name not in BUNDLED_PLUGINS,
        _pinyin_key(display),
        display.lower(),
        manifest.name,
    )


def _pinyin_key(text: str) -> tuple[str, ...]:
    """把文本切成拼音片段用于排序

    - 非汉字片段原样保留，中英混排的标题照该片段比
    """
    from pypinyin import lazy_pinyin

    return tuple(piece.lower() for piece in lazy_pinyin(text))


def panel_needed(code: str) -> bool:
    """判断是否需要自动弹面板

    - 状态缺失、缺目录指纹或指纹与现目录不符，任一为真
    """
    catalog = load_instance_catalog(state_path_of(code), StateKeys.CATALOG)
    if not catalog:
        return True
    roots = plugins_roots()
    if not roots:
        return False
    return catalog_digest(load_manifests(roots)) != catalog


def top_package_name(pin: str) -> str:
    """从依赖 pin 串截出顶层包名"""
    return _PIN_SPLIT.split(pin, 1)[0]
