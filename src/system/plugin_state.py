"""实例插件状态

- 状态块在实例自描述文件里的键名与启用集、目录指纹两键
- 按自描述文件路径读两键，写侧也只替换这一块
"""

from enum import StrEnum
from pathlib import Path

from .profile_env import (
    INSTANCE_PROFILE_NAME,
    profile_dir,
    read_profile_file,
    write_profile_file,
)

# 状态块在自描述文件里的键名
PLUGINS_BLOCK_KEY = "plugins"


class StateKeys(StrEnum):
    """状态块键名

    - 面板写侧与运行期读侧共用
    """

    ENABLED = "enabled"
    CATALOG = "catalog"


def state_path_of(code: str) -> Path:
    """按身份码定位实例自描述文件"""
    return profile_dir(code) / INSTANCE_PROFILE_NAME


def load_instance_enabled(state_path: Path, enabled_key: str) -> frozenset[str] | None:
    """读取实例启用集

    - 没有状态块即实例从未保存过插件选择
    - 名单成员按字符串收，非串成员取它的字面值
    """
    block = _state_block(state_path)
    if block is None:
        return None
    names = block.get(enabled_key, [])
    if not isinstance(names, list):
        return frozenset()
    return frozenset(str(name) for name in names)


def load_instance_catalog(state_path: Path, catalog_key: str) -> str:
    """读取实例目录指纹

    - 缺失或损坏返回空串，与任何现算指纹都不等
    """
    block = _state_block(state_path)
    if block is None:
        return ""
    return str(block.get(catalog_key, ""))


def save_state(state_path: Path, enabled: list[str], catalog: str) -> None:
    """写实例插件状态

    - 随包插件不写进启用集，读取侧恒并入
    - 只替换状态块，自描述文件其余字段原样保留
    - 引导期写入，运行期只读不写
    """
    data = read_profile_file(state_path)
    data[PLUGINS_BLOCK_KEY] = {
        StateKeys.ENABLED: enabled,
        StateKeys.CATALOG: catalog,
    }
    write_profile_file(state_path, data)


def _state_block(state_path: Path) -> dict[str, object] | None:
    """取状态块

    - 块缺失或形状不对交 None，与空块分得开
    """
    block = read_profile_file(state_path).get(PLUGINS_BLOCK_KEY)
    return block if isinstance(block, dict) else None
