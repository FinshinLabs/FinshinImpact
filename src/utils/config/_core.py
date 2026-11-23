"""本体配置项身份

- 本体自用的段名、键名与配置项构造
"""

from enum import StrEnum

from finshin_sdk.domain import ConfigPath, SourceCode

from .sources import SourceKind

_CORE_SOURCE = SourceCode(str(SourceKind.CORE))


class CoreSections(StrEnum):
    """本体自己认的段名"""

    DATA = "data"


class CoreKeys(StrEnum):
    """本体自己认的键名"""

    RECORD_KEEP = "record_keep"
    WAITING = "waiting"


def core_item(key: CoreKeys) -> ConfigPath:
    """本体配置项的完整身份"""
    return ConfigPath(source=_CORE_SOURCE, section=CoreSections.DATA, key=key)
