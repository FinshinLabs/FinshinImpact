"""用例侧的配置段表装配

- 把配置文件指到临时目录，按本实例的来源清单装配一次
- 适配器入口件按给定的标题假造，段默认用 Telegram 实际交出的那两份
"""

import shutil
import tempfile
import unittest
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from adapter_presence import adapter_present

from bot._managers._config_sources import config_sources
from finshin_sdk.domain import SectionSpec
from utils.config import ensure_config

_PARTS_TARGET = "bot._managers._config_sources.parts_for"


def adapter_sections() -> tuple[SectionSpec, ...]:
    """取已装适配器交出的段，未装载即跳过依赖它的用例"""
    if not adapter_present():
        raise unittest.SkipTest("适配层未装载，配置段表用例跳过")
    from finshin_adapter_tg._config import SECTIONS

    return SECTIONS


@contextmanager
def fake_adapter_parts(
    title: str = "Telegram", sections: tuple[SectionSpec, ...] | None = None
) -> Generator[None]:
    """把适配器入口件换成只交标题与段的那一份"""
    parts = Mock(
        spec=["title", "sections"],
        title=title,
        sections=sections if sections is not None else adapter_sections(),
    )
    with patch(_PARTS_TARGET, return_value=parts):
        yield


def assemble_for_case(case: unittest.TestCase) -> Path:
    """装配一次段表，配置文件落临时目录

    - 段表随用例删掉，交回临时目录
    """
    root = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, root, True)
    with (
        patch("utils.config.CONFIG_FILE", root / "config.toml"),
        fake_adapter_parts(),
    ):
        ensure_config(config_sources())
    return root
