"""来源检测协调

- 按来源交出的检测件在后台跑一轮，进度复用检查窗
- 通过记录带输入指纹与实际代理，结论只落本来源
"""

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QWidget

from finshin_sdk.domain import ConnectionPlan, PlanVerdict, ProbeOutcome
from skin.messages import CheckMessage
from utils.check import failure_note, run_probe_round
from utils.config import FieldErrors, ProbeRecord
from utils.logger import get_logger
from utils.network import FrameKey, RowId, RowStatus, opening_rows

from ..._dialogs import Round, current_check_window, open_check_window

if TYPE_CHECKING:
    from ._settings import SettingsController

_logger = get_logger("GUI.Probe")
_orphans: set["_ProbeWorker"] = set()


class _ProbeWorker(QThread):
    """来源检测线程"""

    row_update = Signal(dict)
    done = Signal(object)

    def __init__(
        self,
        plan: ConnectionPlan,
        rows: list[dict],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._plan = plan
        self._rows = rows

    def run(self) -> None:
        """探测线程主循环"""
        try:
            outcome = asyncio.run(
                run_probe_round(
                    self._plan.channels,
                    self.row_update.emit,
                    self._replay,
                    self.isInterruptionRequested,
                )
            )
        except Exception:
            _logger.debug("来源检测线程异常", exc_info=True)
            self.row_update.emit(
                {
                    "id": RowId.ADVICE,
                    "status": RowStatus.FAIL,
                    "detail": CheckMessage.SELF_CRASH,
                }
            )
            self.done.emit(None)
            return
        self.done.emit(outcome)

    def _replay(self) -> None:
        """重跑前重发整表清场"""
        self.row_update.emit(
            {FrameKey.ROWS: self._rows, FrameKey.HEAD: CheckMessage.RETRY_HEAD}
        )


class SourceProbeCoordinator:
    """来源检测协调器

    - 各来源逐轮互斥，通过记录只在面板这一场算数
    """

    def __init__(self, host: "SettingsController") -> None:
        self._host = host
        self._workers: set[_ProbeWorker] = set()
        self._token = 0
        self._group = ""
        self._plan: ConnectionPlan | None = None
        self._done: Callable[[ProbeRecord | None, FieldErrors], None] | None = None
        self._cancelled: Callable[[], None] | None = None
        self.verified: dict[str, ProbeRecord] = {}

    def start(
        self,
        group: str,
        plan: ConnectionPlan,
        on_done: Callable[[ProbeRecord | None, FieldErrors], None],
        on_cancelled: Callable[[], None],
    ) -> bool:
        """按给定计划起一轮检测，返回是否成功开轮"""
        panel = self._host._panel
        busy = current_check_window()
        if (
            panel is None
            or (busy is not None and busy.is_running)
            or any(worker.isRunning() for worker in self._workers)
        ):
            self._host.logger.info(CheckMessage.BUSY)
            return False

        self._token += 1
        self._group = group
        self._plan = plan
        self._done = on_done
        self._cancelled = on_cancelled
        rows = opening_rows(plan)
        win = open_check_window(self._host.gui)
        win.begin_round(Round.PROBE, True, rows, self._on_closed)
        panel.set_busy(True)

        worker = _ProbeWorker(plan, rows, parent=win)
        worker.row_update.connect(lambda f, token=self._token: self._on_frame(token, f))
        worker.done.connect(
            lambda outcome, token=self._token: self._on_done(token, outcome)
        )
        worker.finished.connect(lambda w=worker: self._workers.discard(w))
        self._workers.add(worker)
        worker.start()
        self._host._verify.follow_panel()
        return True

    def _on_frame(self, token: int, frame: dict) -> None:
        """只喂仍在跑的检测轮"""
        if token != self._token:
            return
        win = current_check_window()
        if win is not None and win.round == Round.PROBE:
            win.apply(frame)

    def _on_done(self, token: int, outcome: ProbeOutcome | None) -> None:
        """收检测结论并交保存流程继续"""
        if token != self._token or self._plan is None:
            return
        plan = self._plan
        group = self._group
        done = self._done
        self._plan = None
        self._done = None
        self._cancelled = None
        panel = self._host._panel
        if panel is None or done is None:
            return
        panel.set_busy(False)
        if outcome is None:
            done(None, {})
            return

        verdict = plan.finish(outcome)
        passed = outcome.accepted is not None
        win = current_check_window()
        if win is not None and win.round == Round.PROBE:
            if passed:
                win.settle_and_close(True)
            elif win.is_running:
                win.apply(self._conclusion(verdict, passed))
        panel.apply_source_errors(group, verdict.field_errors)
        self._log_verdict(group, verdict, passed)
        if passed:
            record = ProbeRecord(
                plan.reuse_key,
                outcome.accepted.effective if outcome.accepted else None,
            )
            self.verified[group] = record
            done(record, verdict.field_errors)
        else:
            self.verified.pop(group, None)
            done(None, verdict.field_errors)

    def reset(self) -> None:
        """撤销本场记录与在途检测"""
        self._token += 1
        self.verified.clear()
        self._plan = None
        self._group = ""
        cancelled = self._cancelled
        self._done = None
        self._cancelled = None
        if cancelled is not None:
            cancelled()
        self._abandon_workers()
        win = current_check_window()
        if win is not None and win.round == Round.PROBE and win.is_running:
            win.accept()

    def _on_closed(self, result: int) -> None:
        """关闭检测窗即中止检测，不挂失败标记"""
        if result != QDialog.DialogCode.Rejected:
            return
        self._token += 1
        cancelled = self._cancelled
        self._cancelled = None
        self._done = None
        self._plan = None
        self._abandon_workers()
        panel = self._host._panel
        if panel is not None:
            panel.set_busy(False)
        if cancelled is not None:
            cancelled()

    @staticmethod
    def _conclusion(verdict: PlanVerdict, passed: bool) -> dict:
        """检测结论帧"""
        return {
            "id": RowId.ADVICE,
            "status": RowStatus.OK if passed else RowStatus.FAIL,
            "detail": (
                verdict.notice
                if passed
                else failure_note(verdict.failure_detail, verdict.field_errors)
            ),
        }

    def _log_verdict(self, group: str, verdict: PlanVerdict, passed: bool) -> None:
        """把裁决里的日志句写进面板日志"""
        if verdict.notice:
            self._host.logger.info(verdict.notice)
        if verdict.warning:
            self._host.logger.error(verdict.warning)
        if not passed:
            self._host.logger.error(f"来源 {group} 检测未通过")

    def _abandon_workers(self) -> None:
        """弃用仍在运行的检测线程

        - 解除父级，交 _orphans 养到线程收尾
        """
        for worker in self._workers:
            worker.requestInterruption()
            if worker.isRunning():
                worker.setParent(None)
                _orphans.add(worker)
                worker.finished.connect(lambda w=worker: _orphans.discard(w))
                worker.finished.connect(worker.deleteLater)
        self._workers.clear()
