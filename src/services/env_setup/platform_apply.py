"""平台组件的装卸动作

- 装一批按目录行取件，再一条命令装进运行环境
- 取回的件先按 wheel 元数据声明的接口包要求验一遍，不满足即不装
- 卸一只先数实例，再算只属于那只包的发行件名
"""

from collections.abc import Sequence
from pathlib import Path

from finshin_sdk.domain import platform_of_key
from finshin_sdk.domain.ids import PlatformCode, ProfileKey
from skin.messages import PlatformMessage
from system.distributions import SDK_DISTRIBUTION, installed_version
from system.versions import requires_met

from ..adapter_catalog import ReleaseRow
from ..adapter_manifest import installed_adapters
from ..profile_store import list_profiles
from .deps_keep import keep_union
from .deps_manifest import top_package_name
from .subprocess_ops import ProgressCallback
from .toolchain import GITHUB_MIRRORS, WHEELS_DIR
from .wheel_fetch import download_release
from .wheel_install import WheelFile, install_releases, sdk_requires


def instances_of(platform: PlatformCode) -> int:
    """本机还有几个这一平台的实例

    - 只数身份码前缀等于这一平台码的实例
    """
    return sum(
        1
        for code, _remark in list_profiles()
        if platform_of_key(ProfileKey(code)) == platform
    )


def uninstall_names(platform: PlatformCode) -> tuple[str, ...]:
    """卸一只平台适配器要动的发行件名

    - 适配器包自身，加只有这一只声明过的库
    - 核心依赖、接口包、别的适配器与启用插件点过的库一律留下
    - 只算顶层发行件，传递依赖不在本函数算
    """
    target = next(
        (item for item in installed_adapters() if item.platform == platform), None
    )
    if target is None:
        return ()

    kept = {top_package_name(pin) for pin in keep_union(exclude=target.platform)}
    alone = [
        name for name in map(top_package_name, target.requires) if name not in kept
    ]

    return tuple([target.distribution, *alone])


async def apply_updates(
    releases: Sequence[ReleaseRow], on_line: ProgressCallback | None = None
) -> list[str]:
    """按目录行取件并装进运行环境

    - 交出点名到发行件的失败行
    """
    files: list[WheelFile] = []
    notes: list[str] = []
    for release in releases:
        outcome = await download_release(release, WHEELS_DIR, GITHUB_MIRRORS)
        if outcome.path is None:
            notes.append(outcome.note)
            continue
        gap = _sdk_gap(release, outcome.path)
        if gap:
            notes.append(gap)
            continue
        files.append(WheelFile(outcome.distribution, release.version, outcome.path))

    if files:
        notes.extend(install_releases(files, on_line))

    return notes


def _sdk_gap(release: ReleaseRow, path: Path) -> str:
    """这一版的件要求接口包、本机不满足时的那句

    - 件里没写要求即放行
    - 版本串读不懂也算不满足，宁可先拦下
    """
    requires = sdk_requires(path)
    if not requires:
        return ""

    actual = installed_version(SDK_DISTRIBUTION)
    if actual and requires_met(actual, requires) is True:
        return ""

    template = (
        PlatformMessage.INSTALL_SDK_GAP
        if actual
        else PlatformMessage.INSTALL_SDK_ABSENT
    )
    return template.format(
        name=release.distribution,
        version=release.version,
        requires=requires,
        actual=actual,
    )
