"""网络栈门面

- 按属性惰性解析，取用哪个符号才 import 哪个子模块
- 代发 HTTP 客户端、GitHub 取数通道、链路状态、系统代理与探测协议键符号
- 底层实现分列子模块，与平台无关的校验编排在检查门面
"""

import importlib
from typing import TYPE_CHECKING

_SYMBOL_MODULES = {
    "BaseClient": "._client",
    "GitClient": "._github",
    "LinkStatus": "._link",
    "link_report": "._link",
    "detect_system_proxy": "._proxy",
    "FrameKey": "._probe",
    "RowId": "._probe",
    "RowStatus": "._probe",
    "opening_rows": "._probe",
    "probe_skeleton": "._probe",
    "verify_skeleton": "._probe",
}

__all__ = [
    # HTTP 客户端
    "BaseClient",
    "GitClient",
    # 链路状态
    "LinkStatus",
    "link_report",
    # 系统代理
    "detect_system_proxy",
    # 通道与协议键
    "FrameKey",
    "RowId",
    "RowStatus",
    # 整表铺送
    "opening_rows",
    "probe_skeleton",
    "verify_skeleton",
]

if TYPE_CHECKING:
    from ._client import BaseClient
    from ._github import GitClient
    from ._link import LinkStatus, link_report
    from ._probe import (
        FrameKey,
        RowId,
        RowStatus,
        opening_rows,
        probe_skeleton,
        verify_skeleton,
    )
    from ._proxy import detect_system_proxy


def __getattr__(name: str) -> object:
    module_path = _SYMBOL_MODULES.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_path, __name__)
    return getattr(module, name)
