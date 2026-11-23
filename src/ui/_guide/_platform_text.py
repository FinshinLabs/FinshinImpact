"""平台组件面板的读数文案

- 来源、来路、版本与版本窗状态各交一句给人看的话
- 该装哪版挡不挡的结算在服务层，这里只把结果写成句子
"""

from collections.abc import Sequence

from services.adapter_catalog import ReleaseRow
from services.env_setup.platform_rows import ComponentRow, ComponentSource
from services.env_setup.platform_state import (
    ComponentOrigin,
    VersionEntry,
    VersionState,
    release_blocked,
)
from skin.messages import PlatformMessage

# 来源四档给人看的那句
_SOURCE_TEXT = {
    ComponentSource.TREE_INSTALLED: PlatformMessage.SOURCE_TREE_INSTALLED,
    ComponentSource.TREE_ONLY: PlatformMessage.SOURCE_TREE_ONLY,
    ComponentSource.INSTALLED: PlatformMessage.LOCAL_INSTALLED,
    ComponentSource.NONE: PlatformMessage.SOURCE_NONE,
}

# 来路三档给人看的那句，没得取的档位不进表
_ORIGIN_TEXT = {
    ComponentOrigin.WHEEL: PlatformMessage.ORIGIN_WHEEL,
    ComponentOrigin.CATALOG: PlatformMessage.ORIGIN_CATALOG,
    ComponentOrigin.TREE: PlatformMessage.ORIGIN_TREE,
}


def name_text(row: ComponentRow) -> str:
    """块首行的组件名

    - 适配器与接口包各用一句模板填发行件名
    """
    template = (
        PlatformMessage.NAME_SDK if not row.platform else PlatformMessage.NAME_ADAPTER
    )
    return template.format(name=row.distribution)


def source_text(row: ComponentRow) -> str:
    """来源那一句

    - 按源码仓在不在场与包有没有装进环境选句
    """
    return _SOURCE_TEXT[row.source]


def origin_text(origin: ComponentOrigin, version: str) -> str:
    """来路那一句

    - 点名取的是哪一版，没这一档即交空串
    """
    template = _ORIGIN_TEXT.get(origin)
    return template.format(version=version) if template else ""


def version_text(row: ComponentRow) -> str:
    """版本行正文

    - 在线那档说目录里最新的那一版
    """
    newest = row.release
    if newest is None:
        return row.installed or PlatformMessage.LINE_ABSENT
    if not row.installed:
        return PlatformMessage.LINE_VERSIONS_ABSENT.format(available=newest.version)

    return PlatformMessage.LINE_VERSIONS.format(
        installed=row.installed, available=newest.version
    )


def version_state_text(entry: VersionEntry) -> str:
    """版本窗左清单里那一版的状态

    - 按环境里已装、盘上件核过、只能走网络分三档
    """
    return {
        VersionState.CURRENT: PlatformMessage.VERSION_CURRENT,
        VersionState.LOCAL: PlatformMessage.VERSION_LOCAL,
        VersionState.NETWORK: PlatformMessage.VERSION_NETWORK,
    }[entry.state]


def row_note(
    rows: Sequence[ComponentRow], row: ComponentRow, target: ReleaseRow | None
) -> str:
    """装不了的那句原因

    - 能装就交空串
    - 该装的那版被接口包要求挡住即点名那一版
    """
    if target is None:
        return ""

    return release_blocked(rows, row, target)


def action_text(row: ComponentRow) -> str:
    """动作栏按钮的文案"""
    return (
        PlatformMessage.BTN_INSTALL if not row.installed else PlatformMessage.BTN_APPLY
    )
