"""平台组件的装与挡

- 一键更新的那批只收在线比本机新、且目标版挡装判据放行的行
- 适配器要接口包已在本机，且落在要装那一版声明的要求之内
- 接口包要求那一行的说法按本机接口包版本定
- 版本窗逐版只报本机状态，挡不挡由同一条判据现算
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from skin.messages import PlatformMessage
from system.distributions import SDK_DISTRIBUTION, installed_version
from system.versions import over_ceiling, requires_met

from ..adapter_catalog import ReleaseRow
from .platform_rows import ComponentBucket, ComponentRow, ComponentSource
from .toolchain import WHEELS_DIR
from .wheel_fetch import is_cached


class ComponentOrigin(StrEnum):
    """一行摆的内容从哪儿取到

    - WHEEL 盘上那份件指纹对得上目录，装它不联网
    - CATALOG 只有在线目录的直链，装它要走网络
    - TREE 没有目录行，只有挂载的源码仓在场
    - NONE 本机既没有目录行也没有源码仓
    """

    WHEEL = "wheel"
    CATALOG = "catalog"
    TREE = "tree"
    NONE = "none"


class VersionState(StrEnum):
    """一版在本机的状态

    - CURRENT 环境里就是这一版
    - LOCAL 盘上那份件指纹核过，装它从本机取
    - NETWORK 盘上没有这一版，只能从网络装
    """

    CURRENT = "current"
    LOCAL = "local"
    NETWORK = "network"


@dataclass(frozen=True, slots=True)
class VersionEntry:
    """版本窗里一版的读数

    - state 按环境里是不是这一版、盘上那份件核没核到指纹定
    """

    release: ReleaseRow
    state: VersionState


def update_targets(rows: Sequence[ComponentRow]) -> list[ReleaseRow]:
    """一键更新的那批目录行

    - 只收在线比本机新的
    - 本机没装过的不进这一批
    - 目标版挡装判据不放行的不进这一批
    """
    targets: list[ReleaseRow] = []
    for row in rows:
        if row.bucket != ComponentBucket.UPGRADABLE:
            continue
        target = update_target(rows, row)
        if target is not None and not release_blocked(rows, row, target):
            targets.append(target)

    return targets


def update_target(rows: Sequence[ComponentRow], row: ComponentRow) -> ReleaseRow | None:
    """这一行该装的那一版

    - 接口包那行只报读数，交出 None
    - 适配器那行取目录最新一版
    """
    if not row.platform:
        return None

    return row.release


def release_blocked(
    rows: Sequence[ComponentRow], row: ComponentRow, release: ReleaseRow
) -> str:
    """适配器这一版的挡装理由

    - 能装交出空串
    - 按本机接口包落在不在这一版声明的要求之内判
    """
    return _install_blocked(rows, row, release)


def _install_blocked(
    rows: Sequence[ComponentRow], row: ComponentRow, release: ReleaseRow
) -> str:
    """这只适配器这一版的挡装下一步

    - 能装交出空串
    - 要接口包已在本机，且落在要装那一版声明的要求之内
    - 那一版没写要求即按本机已装适配器的声明判
    - 版本串读不懂算没到位
    """
    sdk = next((item for item in rows if not item.platform), None)
    if sdk is None or not sdk.installed:
        return PlatformMessage.NEED_SDK_INSTALL
    requires = release.sdk_requires or row.requires
    if requires_met(sdk.installed, requires):
        return ""
    if over_ceiling(sdk.installed, requires):
        return PlatformMessage.SDK_TOO_NEW

    return PlatformMessage.NEED_SDK_UPDATE


def source_origin(rows: Sequence[ComponentRow], row: ComponentRow) -> ComponentOrigin:
    """一行内容的来路

    - 按该装的那一版的件在不在盘上定
    - 没有该装的那一版时，源码仓挂着只说明声明读得到
    """
    target = update_target(rows, row)
    if target is None:
        in_tree = row.source in (
            ComponentSource.TREE_INSTALLED,
            ComponentSource.TREE_ONLY,
        )
        return ComponentOrigin.TREE if in_tree else ComponentOrigin.NONE
    if is_cached(target, WHEELS_DIR):
        return ComponentOrigin.WHEEL

    return ComponentOrigin.CATALOG


def version_entries(row: ComponentRow) -> tuple[VersionEntry, ...]:
    """版本窗里逐版的读数

    - 没有目录行即没有清单可列
    - 逐版按本机环境与盘上那份件定
    """
    if row.release is None:
        return ()

    return tuple(
        VersionEntry(release=item, state=_version_state(item, row))
        for item in row.release.versions
    )


def _version_state(item: ReleaseRow, row: ComponentRow) -> VersionState:
    """一版在本机的状态

    - 环境里就是这一版优先于盘上那份件
    """
    if row.installed and item.version == row.installed:
        return VersionState.CURRENT
    if is_cached(item, WHEELS_DIR):
        return VersionState.LOCAL

    return VersionState.NETWORK


def deps_text(row: ComponentRow) -> str:
    """接口包要求那一行的正文

    - 说法按本机接口包版本定
    - 本机没在场的行没有要求可报
    """
    if row.source == ComponentSource.NONE:
        return ""
    if not row.requires:
        return PlatformMessage.REQUIRES_NONE

    actual = installed_version(SDK_DISTRIBUTION)
    if not actual:
        return PlatformMessage.REQUIRES_NO_SDK.format(requires=row.requires)

    met = requires_met(actual, row.requires)
    if met is None:
        return PlatformMessage.REQUIRES_UNREADABLE.format(requires=row.requires)

    return (
        PlatformMessage.REQUIRES_MET if met else PlatformMessage.REQUIRES_GAP
    ).format(requires=row.requires, actual=actual)
