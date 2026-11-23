"""配置控制器

- 向导调度、按来源保存与完成判定
- EDIT/SETUP 同实例原地切换，失败不丢已填内容
- 保存、检测与启动校验各交一只协调器
"""

from skin.messages import CheckMessage, DialogMessage
from skin.theme import SETTINGS_DIALOG
from utils import config_manager
from utils.config import FieldErrors, ProbeRecord, validate_types

from ..._bridge import gui_bridge
from ..._dialogs import (
    ConfigMode,
    NoticeDialog,
    SettingsDialog,
    close_restart_wait,
    current_check_window,
    finish_restart_wait,
    show_restart_wait,
)
from ..._lifecycle import Ticker
from ._base import BaseController
from ._save import SaveCoordinator
from ._source_probe import SourceProbeCoordinator
from ._verify import VerifyCoordinator

_STARTUP_WAIT_DELAY = 1200  # 启动校验 1.2 秒后才弹等待窗


class SettingsController(BaseController):
    """配置控制器"""

    LOGGER_NAME = "GUI.Settings"
    BTN_KEY = "settings"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._current_mode: ConfigMode = ConfigMode.EDIT
        self._is_dialog_open = False
        self._field_errors: FieldErrors = {}
        self._panel: SettingsDialog | None = None
        self._config_ready = False
        self._verify = VerifyCoordinator(self)
        self._save = SaveCoordinator(self)
        self._probe = SourceProbeCoordinator(self)

        gui_bridge.config_ready_changed.connect(
            self._on_config_ready_changed, "配置就绪", queued=True
        )
        gui_bridge.verify_progress.connect(
            self._verify.on_frame, "校验进度", queued=True
        )
        gui_bridge.service_restarting.connect(
            self._on_service_restarting, "服务重启", queued=True
        )
        gui_bridge.config_source_done.connect(
            self.source_done, DialogMessage.SETTINGS_SIGNAL_SOURCE_DONE, queued=True
        )

    def _on_service_restarting(self, restarting: bool) -> None:
        """起收热重启等待窗"""
        if restarting:
            show_restart_wait(self.gui)
        else:
            close_restart_wait()

    def _on_config_ready_changed(self, ready: bool) -> None:
        """收启动校验，按类保存的结果另走 source_done"""
        self._config_ready = ready
        if not ready:
            if not (self._panel or current_check_window()):
                Ticker.after(_STARTUP_WAIT_DELAY, self._verify.open_startup_wait)
            return
        if self._save.busy:
            return

        self._verify.validating = False
        self._verify.pending_aborts = None
        wait = self._verify.window()
        if wait is not None:
            wait.accept()
        finish_restart_wait(SETTINGS_DIALOG.verified_ok)

    def source_done(
        self,
        group: str,
        ok: bool,
        errors: object,
        record: object,
    ) -> None:
        """收 Manager 的单类保存结果并刷新本窗口"""
        panel = self._panel
        if panel is None:
            return
        was_setup = panel.is_setup
        self._save.source_done(
            panel,
            group,
            ok,
            dict(errors) if isinstance(errors, dict) else {},
            record if isinstance(record, ProbeRecord) else None,
        )
        if ok:
            # 保存期间 config_ready 那条路被 busy 挡下，校验窗的绿结论由这里替用户收掉
            wait = self._verify.window()
            if wait is not None and wait.settled and wait.isVisible():
                wait.accept()
            if was_setup and not panel.is_setup:
                outcome = SETTINGS_DIALOG.setup_all_passed
            elif not self._save.wrote:
                outcome = SETTINGS_DIALOG.recheck_ok
            elif panel.is_setup:
                outcome = SETTINGS_DIALOG.source_saved
            elif self._save.identity_changed:
                outcome = SETTINGS_DIALOG.history_reset
            else:
                outcome = SETTINGS_DIALOG.verified_ok
            self._save.identity_changed = False
            if not finish_restart_wait(outcome):
                NoticeDialog.notify(outcome, parent=panel)
        else:
            close_restart_wait()

    def _execute(self) -> None:
        """用户点击按钮进入编辑模式"""
        if not self._config_ready:
            self.logger.info(CheckMessage.NOT_READY)
            return
        self._current_mode = ConfigMode.EDIT
        self._field_errors = {}
        self._show_dialog()

    def show_setup_dialog(self, field_errors: FieldErrors | None = None) -> None:
        """强制向导进场只按盘上值算一遍字段错"""
        if gui_bridge.is_shutdown_pending():
            self.logger.info("关闭流程进行中，跳过强制配置向导")
            return

        local_errors = validate_types(config_manager.schema, config_manager.get_all())
        self._field_errors = {**local_errors, **dict(field_errors or {})}
        if self._panel is not None:
            self._verify.drop_pending()
            self._panel.set_busy(False)
            if self._current_mode == ConfigMode.EDIT:
                self._current_mode = ConfigMode.SETUP
                self._panel.switch_to_setup(self._field_errors)
                self.logger.info("校验未过，面板已原地转强制向导")
            else:
                self._panel.apply_errors(self._field_errors)
            self._verify.follow_panel()
            return

        self._current_mode = ConfigMode.SETUP
        self._show_dialog()

    def _show_dialog(self) -> None:
        """打开配置弹窗"""
        if self._is_dialog_open:
            if self._panel is not None:
                self._panel.raise_()
                self._panel.activateWindow()
                self.logger.info("配置面板已打开，置前显示")
            return
        self._is_dialog_open = True
        self.logger.info("正在打开配置面板...")
        self._panel = self._create_dialog()
        self._save.reset_pending()
        dialog = self._panel
        dialog.save_requested.connect(lambda group: self._save.requested(dialog, group))
        dialog.finish_requested.connect(lambda: self._save.finish(dialog))
        dialog.finished.connect(self._on_panel_finished)
        dialog.show()
        self._verify.follow_panel()

    def _create_dialog(self) -> SettingsDialog:
        """按当前模式构造配置弹窗"""
        return SettingsDialog(
            schema=config_manager.schema,
            current_config=config_manager.get_all(),
            mode=self._current_mode,
            parent=self.gui,
            field_errors=self._field_errors,
        )

    def _on_panel_finished(self, result: int) -> None:
        """面板关闭后撤销本场状态"""
        if self._panel is None:
            return
        if result == self._panel.DialogCode.Rejected:
            self.logger.info("用户取消配置修改")
        self._save.close()
        self._probe.reset()
        self._panel.deleteLater()
        self._panel = None
        self._is_dialog_open = False
