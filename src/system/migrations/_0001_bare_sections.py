"""裸段配置搬进来源块

- 1.0.0-alpha.7.dev7 及更早 → 1.0.0-alpha.7.dev8 起的布局
- 顶层 proxy/model/ai/chore/data 搬进对应来源块，键名与值不改
- 新段已有值为准，旧写法只补缺
- 不认识的内容原样保留
"""

from typing import Any

FROM_RELEASE = "1.0.0-alpha.7.dev7 及更早"
TO_RELEASE = "1.0.0-alpha.7.dev8 起"

# 旧裸段到新段名的对照表。顺序决定多个旧段争同一键时谁先落定
_MAPPING: tuple[tuple[str, str, str], ...] = (
    ("proxy", "adapter.tg", "proxy"),
    ("model", "plugin.AI", "model"),
    ("ai", "plugin.AI", "model"),
    ("chore", "plugin.AI", "chore"),
    ("data", "core", "data"),
)

_OLD_SECTIONS = tuple(old for old, _, _ in _MAPPING)


def matches(document: dict[str, Any]) -> bool:
    """顶层还留着旧段、且来源块位置没被占成别的形状时命中"""
    if "source" in document and not isinstance(document["source"], list):
        return False
    return any(isinstance(document.get(old), dict) for old in _OLD_SECTIONS)


def apply(document: dict[str, Any]) -> list[str]:
    """按对照表搬段，交出逐条说明"""
    notes: list[str] = []
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
    _report_unknown(document, notes)
    return notes


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


def _report_unknown(document: dict[str, Any], notes: list[str]) -> None:
    for name, value in document.items():
        if name == "source":
            continue
        kind = "段" if isinstance(value, dict) else "键"
        notes.append(f"未识别{kind} {name}，原样保留")
