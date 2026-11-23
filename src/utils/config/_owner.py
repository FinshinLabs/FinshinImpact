"""主人配置项解析"""

from collections.abc import Sequence
from typing import Protocol, TypeVar

from finshin_sdk.domain import ConfigPath, SourceCode

from .sources import current_plan

# 字段声明里标记主人配置项的标签名
OWNER_TAG = "owner"


class _Tagged(Protocol):
    """带用途标记的字段"""

    @property
    def tags(self) -> tuple[str, ...]: ...


_T = TypeVar("_T", bound=_Tagged)


def owner_field(fields: Sequence[_T]) -> _T | None:
    """取字段表里第一条带主人标记的字段"""
    return next((field for field in fields if OWNER_TAG in field.tags), None)


def owner_item() -> ConfigPath | None:
    """交主人配置项的身份

    - 没有这一条即交 None
    """
    plan = current_plan()
    if plan is None:
        return None
    for item in plan.sections:
        spec = owner_field(item.spec.fields)
        if spec is not None:
            return ConfigPath(
                source=SourceCode(item.identity), section=spec.section, key=spec.key
            )
    return None
