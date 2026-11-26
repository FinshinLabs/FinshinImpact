"""通用工具门面

- 代发配置管理器
"""

import importlib
from typing import TYPE_CHECKING

# 身份码未定前导入会抛错，故按取用触发
_SYMBOL_MODULES = {
    "config_manager": "._config_manager",
}

if TYPE_CHECKING:
    from ._config_manager import config_manager


def __getattr__(name: str) -> object:
    module_path = _SYMBOL_MODULES.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)
