"""网络栈门面

- 代发 HTTP 客户端、GitHub 取数通道、链路状态、系统代理、探测协议键与进度行状态符号
"""

import importlib
from typing import TYPE_CHECKING

from finshin_sdk.domain import RowStatus

_SYMBOL_MODULES = {
    "BaseClient": "._client",
    "GitClient": "._github",
    "LinkStatus": "._link",
    "link_report": "._link",
    "detect_system_proxy": "._proxy",
    "CHECKING": "._probe",
    "FrameKey": "._probe",
    "RowId": "._probe",
    "opening_rows": "._probe",
    "probe_skeleton": "._probe",
    "verify_skeleton": "._probe",
}

if TYPE_CHECKING:
    from ._client import BaseClient
    from ._github import GitClient
    from ._link import LinkStatus, link_report
    from ._probe import (
        CHECKING,
        FrameKey,
        RowId,
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
