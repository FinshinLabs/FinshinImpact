"""wheel 发行件装进运行环境

- 一条命令带全部 wheel 与 --find-links，本地包互相喂依赖
- 逐只点名重装
- 整批失败转逐只重试，收集装不进的发行件
- 依赖被判无解即整批记失败，不再逐只重试
- 只复核装上的件：按本机读到的版本对不上即点名，不报成功
- 另交一只 wheel 元数据里声明的接口包要求，装机前先按它拦
"""

import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from skin.messages import CatalogMessage, PlatformMessage
from system.distributions import SDK_DISTRIBUTION, installed_version, requires_of

from .subprocess_ops import ProgressCallback, degraded, with_index_retry
from .toolchain import PIP_FLAGS, WHEELS_DIR, dev_mode, uv_cmd


@dataclass(frozen=True, slots=True)
class WheelFile:
    """一只落到盘上的 wheel 件

    - distribution 与 version 用于点名复核，path 用于交给 uv
    """

    distribution: str
    version: str
    path: Path


def _install_flags(files: Sequence[WheelFile]) -> list[str]:
    """拼一次装 wheel 的 uv 参数

    - 逐只点名重装
    """
    return [
        "pip",
        "install",
        *PIP_FLAGS,
        "--find-links",
        str(WHEELS_DIR),
        "--link-mode",
        "copy",
        "--no-progress",
        "--compile-bytecode",
    ] + [f"--reinstall-package={item.distribution}" for item in files]


def install_releases(
    files: Sequence[WheelFile], on_line: ProgressCallback | None = None
) -> list[str]:
    """把 wheel 装进运行环境

    - 交出装不进的说明行
    - 一条命令带全部件，本地包互相喂依赖，逐只点名重装
    - 整批失败转逐只重试，逐只点名
    - 依赖无解即整批记失败，不再逐只重试
    - 只复核装上的件：按本机读到的版本对不上即点名
    - 开发模式只交等效手动命令
    """
    if not files:
        return []

    paths = [str(item.path) for item in files]
    if dev_mode():
        degraded(
            [uv_cmd(f"pip install --find-links {WHEELS_DIR} " + " ".join(paths))],
            on_line,
        )
        return [
            CatalogMessage.INSTALL_FAILED.format(
                name=item.distribution, version=item.version
            )
            for item in files
        ]

    base = _install_flags(files)
    failed: list[str] = []
    uninstalled: set[str] = set()
    code, unresolved = with_index_retry([*base, *paths], on_line)
    if code != 0 and unresolved:
        uninstalled.update(item.distribution for item in files)
        failed.extend(
            CatalogMessage.INSTALL_FAILED.format(
                name=item.distribution, version=item.version
            )
            for item in files
        )
    elif code != 0:
        for item in files:
            if (
                with_index_retry([*_install_flags([item]), str(item.path)], on_line)[0]
                != 0
            ):
                uninstalled.add(item.distribution)
                failed.append(
                    CatalogMessage.INSTALL_FAILED.format(
                        name=item.distribution, version=item.version
                    )
                )

    for item in files:
        if item.distribution in uninstalled:
            continue
        found = installed_version(item.distribution)
        if found != item.version:
            failed.append(
                PlatformMessage.APPLY_MISMATCH.format(
                    name=item.distribution, found=found or "没读到", wanted=item.version
                )
            )

    return failed


def sdk_requires(path: Path) -> str:
    """wheel 元数据里声明的接口包要求

    - 元数据读不出或没声明要求即交空串
    """
    try:
        with zipfile.ZipFile(path) as archive:
            name = next(
                (
                    item
                    for item in archive.namelist()
                    if item.endswith(".dist-info/METADATA")
                ),
                "",
            )
            if not name:
                return ""
            text = archive.read(name).decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""

    pins: list[str] = []
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "requires-dist":
            pins.append(value.strip())

    return requires_of(pins, SDK_DISTRIBUTION)
