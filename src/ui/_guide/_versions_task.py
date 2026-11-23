"""平台组件「其他版本」的取数线程

- 取到交出全部正式 release，取不到交出一行给人看的原因
- 失败原文进运行日志，屏上只留异常族给的那句原因
"""

import asyncio
import traceback

from PySide6.QtCore import QThread, Signal

from exceptions import VersionError, describe_error
from services.env_setup.subprocess_ops import log_ops
from services.release_feed import component_notes
from skin.messages import PlatformMessage


class VersionsTask(QThread):
    """一只组件仓的发布正文取数线程"""

    reported = Signal(object, str)

    def __init__(self, release_url: str) -> None:
        super().__init__()
        self._url = release_url

    def run(self) -> None:
        """取一次这只仓的正式 release

        - 取不到时交回一行原因
        """
        try:
            self.reported.emit(asyncio.run(component_notes(self._url)), "")
        except VersionError as e:
            log_ops(traceback.format_exception(e))
            self.reported.emit(
                None,
                PlatformMessage.VERSIONS_FETCH_FAILED.format(reason=describe_error(e)),
            )
        except Exception as e:
            log_ops([f"[task:versions] {type(e).__name__}: {e}"])
            self.reported.emit(
                None,
                PlatformMessage.VERSIONS_FETCH_FAILED.format(reason=type(e).__name__),
            )
