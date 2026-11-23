"""旧布局整成当前形状

- 顶层 proxy/model/ai/chore/data 搬进来源块，键名与值不改
- plugins.toml 的启用集与目录指纹搬进 profile.json 的 plugins 块
- 新位置已有值为准，旧写法只补缺
- 旧插件状态文件改名留底，不认识的内容原样保留
"""

import shutil
import tomllib
from pathlib import Path
from typing import Any

from ..plugin_state import PLUGINS_BLOCK_KEY, StateKeys, save_state
from ..profile_env import INSTANCE_PROFILE_NAME, read_profile_file
from ._runner import MigrationInstance

# 旧裸段到新段名的对照表。顺序决定多个旧段争同一键时谁先落定
_MAPPING: tuple[tuple[str, str, str], ...] = (
    ("proxy", "adapter.tg", "proxy"),
    ("model", "plugin.AI", "model"),
    ("ai", "plugin.AI", "model"),
    ("chore", "plugin.AI", "chore"),
    ("data", "core", "data"),
)

_OLD_SECTIONS = tuple(old for old, _, _ in _MAPPING)

# 旧插件状态文件与备份后缀
_OLD_STATE_NAME = "plugins.toml"
_BACKUP_SUFFIX = ".bak"


def matches(instance: MigrationInstance) -> bool:
    """两样旧形状任一在场即命中"""
    return (
        _has_bare_sections(instance.document)
        or (instance.root / _OLD_STATE_NAME).is_file()
    )


def apply(instance: MigrationInstance) -> tuple[bool, list[str]]:
    """按对照表搬段、旧插件状态并进自描述文件，交出「动过」与逐条说明"""
    notes: list[str] = []
    moved = _move_bare_sections(instance.document, notes)
    moved = _move_plugin_state(instance.root, notes) or moved
    return moved, notes


def _has_bare_sections(document: dict[str, Any]) -> bool:
    """顶层还留着旧段、且来源块位置没被占成别的形状"""
    if "source" in document and not isinstance(document["source"], list):
        return False
    return any(isinstance(document.get(old), dict) for old in _OLD_SECTIONS)


def _move_bare_sections(document: dict[str, Any], notes: list[str]) -> bool:
    """按对照表搬段，交出是否动过"""
    if not _has_bare_sections(document):
        return False
    blocks: list[Any] = document.setdefault("source", [])
    for old, identity, section in _MAPPING:
        if old not in document:
            continue
        value = document[old]
        if not isinstance(value, dict):
            notes.append(f"顶层 {old} 不是表，原样保留")
            continue
        block: dict[str, Any] | None = _find_block(blocks, identity)
        if block is None:
            block = {"id": identity}
            blocks.append(block)
        target: dict[str, Any] = block.setdefault(section, {})
        notes.append(f"搬 [{old}] -> {identity}.{section}")
        _merge_missing(target, value, f"{identity}.{section}", notes)
        del document[old]
    return True


def _find_block(blocks: list[Any], identity: str) -> dict[str, Any] | None:
    for element in blocks:
        if isinstance(element, dict) and str(element.get("id", "")) == identity:
            return element
    return None


def _merge_missing(
    target: dict[str, Any],
    source: dict[str, Any],
    path: str,
    notes: list[str],
) -> None:
    for key, value in source.items():
        if key not in target:
            target[key] = value
            notes.append(f"  {path}.{key} 取旧值")
        elif isinstance(target[key], dict) and isinstance(value, dict):
            _merge_missing(target[key], value, f"{path}.{key}", notes)
        else:
            notes.append(f"  {path}.{key} 新段已有值，旧值不采用")


def _move_plugin_state(root: Path, notes: list[str]) -> bool:
    """把旧插件状态搬进自描述文件，交出是否动过

    - 自描述文件读不出即两者都不动
    - 写盘失败不动旧文件
    """
    old = root / _OLD_STATE_NAME
    if not old.is_file():
        return False
    profile = root / INSTANCE_PROFILE_NAME
    data = read_profile_file(profile)
    if not data:
        notes.append(f"{INSTANCE_PROFILE_NAME} 读不出，插件状态未动")
        return False

    if PLUGINS_BLOCK_KEY in data:
        notes.extend(_retired(old, "插件状态新位置已有值，旧文件改名留底"))
        return True

    try:
        document = tomllib.loads(old.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        notes.append(f"{_OLD_STATE_NAME} 读不出，未动（{e}）")
        return False

    raw = document.get(StateKeys.ENABLED, [])
    enabled = [str(item) for item in raw] if isinstance(raw, list) else []
    catalog = str(document.get(StateKeys.CATALOG, ""))

    backup = profile.with_name(profile.name + _BACKUP_SUFFIX)
    try:
        if not backup.exists():
            shutil.copyfile(profile, backup)
        save_state(profile, enabled, catalog)
    except OSError as e:
        notes.append(f"插件状态未写盘（{e}）")
        return False

    notes.extend(
        _retired(old, f"插件状态已并进 {INSTANCE_PROFILE_NAME}，旧文件改名留底")
    )
    return True


def _retired(old: Path, done: str) -> list[str]:
    """旧文件改名留底，改名失败时那句「改名留底」不写"""
    target = old.with_name(old.name + _BACKUP_SUFFIX)
    try:
        target.unlink(missing_ok=True)
        old.rename(target)
    except OSError as e:
        return [f"旧文件改名未成（{e}）"]

    return [done]
