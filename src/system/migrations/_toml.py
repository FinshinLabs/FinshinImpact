"""配置文本渲染

- 迁移写回用，只靠标准库，启动器装依赖之前也能跑
- 表头与键按原层级展开，字符串与控制符统一转义
"""

import re
from datetime import date, datetime, time
from typing import Any

# TOML bare key 字符集，集外的键名与表头段名一律加双引号
_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")

# basic string 的单字符转义，表外控制符走 \u00XX
_STRING_ESCAPES = {
    '"': '\\"',
    "\\": "\\\\",
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def render(document: dict[str, Any]) -> str:
    """整份配置渲染成 TOML 文本"""
    units: list[str] = []
    for name, value in document.items():
        if _is_table(value):
            continue
        units.append(f"{_key(name)} = {_value(value)}")
    for name, value in document.items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _emit_table((name,), item, units, array=True)
        elif isinstance(value, dict):
            _emit_table((name,), value, units)
    return ("\n\n".join(units) + "\n") if units else ""


def _emit_table(
    header: tuple[str, ...],
    table: dict[str, Any],
    units: list[str],
    *,
    array: bool = False,
) -> None:
    head = f"[[{_header(header)}]]" if array else f"[{_header(header)}]"
    rows = [f"{_key(k)} = {_value(v)}" for k, v in table.items() if not _is_table(v)]
    units.append(head + ("\n" + "\n".join(rows) if rows else ""))
    for key, value in table.items():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _emit_table((*header, key), item, units, array=True)
        elif isinstance(value, dict):
            _emit_table((*header, key), value, units)


def _header(parts: tuple[str, ...]) -> str:
    return ".".join(_key(part) for part in parts)


def _is_table(value: Any) -> bool:
    if isinstance(value, dict):
        return True
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, dict) for item in value)
    )


def _value(value: Any) -> str:
    if isinstance(value, str):
        return _str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (datetime, date, time)):
        stamp = value.isoformat()
        return f"{stamp[:-6]}Z" if stamp.endswith("+00:00") else stamp
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in value.items())
            + " }"
        )
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    raise TypeError(f"不支持的值：{type(value).__name__}")


def _key(key: str) -> str:
    return key if _BARE_KEY.fullmatch(key) else _str(key)


def _str(value: str) -> str:
    parts: list[str] = []
    for char in value:
        escape = _STRING_ESCAPES.get(char)
        if escape:
            parts.append(escape)
        elif char < " " or char == "\x7f":
            parts.append(f"\\u{ord(char):04x}")
        else:
            parts.append(char)
    return '"' + "".join(parts) + '"'
