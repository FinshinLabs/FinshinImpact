"""按来源保存与完成判定

- 先确认本类变更，再本地校验与本类检测，通过才写盘
- 完成时拦住未存改动，丢弃只退回本场磁盘快照
"""

from typing import TYPE_CHECKING

from skin.messages import CheckMessage, DialogMessage
from utils import config_manager
from utils.config import (
    ProbeRecord,
    SourceSaveRequest,
    compare_configs,
    merge_source_config,
    owner_item,
    validate_types,
)
from utils.config.models import AppConfigData, FieldErrors
from utils.config.sources import section_name

from ..._bridge import gui_bridge
from ..._dialogs import ChangeConfirmDialog, NoticeDialog, SettingsDialog

if TYPE_CHECKING:
    from ._settings import SettingsController


class SaveCoordinator:
    """保存流程协调器

    - 一次只处理一个大类，检测与写盘共用同一忙位
    """

    def __init__(self, host: "SettingsController") -> None:
        self._host = host
        self._busy = False
        self._pending_group = ""
        self._candidate: AppConfigData = {}
        self.wrote = False
        self.identity_changed = False
        self._pending_apply = False

    @property
    def busy(self) -> bool:
        """是否有保存或检测在途"""
        return self._busy

    def reset_pending(self) -> None:
        """清零本次开窗的待应用状态"""
        self._pending_apply = False

    def requested(self, dialog: SettingsDialog | None, group: str) -> None:
        """按来源走确认、本地校验、检测与写盘"""
        host = self._host
        if dialog is None or self._busy or dialog is not host._panel:
            return

        candidate = dialog.get_modified_config()
        dirty = group in dialog.dirty_groups
        warning = group in dialog.warning_groups
        if not dirty and not warning:
            NoticeDialog.notify(DialogMessage.SETUP_NO_CHANGE, parent=dialog)
            return

        disk = dialog.disk_values()
        if dirty:
            changes, logs = compare_configs(
                config_manager.schema, disk, candidate, group=group
            )
            if not ChangeConfirmDialog.confirm(logs, parent=dialog):
                return
            self.log_changes(logs)
            self._remember_identity(changes)

        errors = validate_types(config_manager.schema, candidate, group=group)
        if errors:
            dialog.mark_source_failed(group, errors)
            return

        source_candidate = merge_source_config(
            config_manager.schema, disk, group, candidate
        )
        self._busy = True
        self._pending_group = group
        dialog.set_busy(True)
        host._verify.validating = True
        host._verify.pending_aborts = True
        host.logger.debug(
            CheckMessage.VERIFY_START.format(reason=CheckMessage.REASON_SAVE)
        )

        try:
            plan = dialog.probe_plan(group, source_candidate)
        except Exception as exc:
            host.logger.send_error(f"来源 {group} 的检测计划造不出来", exc)
            self._failed(dialog, group, {})
            return
        if plan is None:
            self._dispatch(dialog, group, source_candidate, dirty)
            return

        def passed(record: ProbeRecord | None, errors: FieldErrors) -> None:
            if not self._owns(dialog, group):
                return
            if record is None:
                self._failed(dialog, group, errors)
                return
            self._dispatch(dialog, group, source_candidate, dirty)

        started = host._probe.start(group, plan, passed, lambda: self.cancelled())
        if not started:
            self.cancelled()

    def finish(self, dialog: SettingsDialog | None) -> None:
        """处理完成、未存清单与丢弃"""
        if dialog is None or self._busy or dialog is not self._host._panel:
            return
        dirty = dialog.dirty_groups
        if dirty:
            titles = "、".join(dialog.group_title(group) for group in dirty)
            tip = DialogMessage.SETUP_UNSAVED.format(n=len(dirty), groups=titles)
            accepted = ChangeConfirmDialog.confirm(
                [],
                parent=dialog,
                title=DialogMessage.SETUP_TITLE,
                tip=tip,
                cancel_text=DialogMessage.BTN_RETURN,
                confirm_text=DialogMessage.BTN_DISCARD,
            )
            if not accepted:
                return
            dialog.restore_disk()

        if self._pending_apply:
            gui_bridge.config_sources_verified.emit(dict(self._host._probe.verified))
            self._pending_apply = False
        dialog.accept()

    def source_done(
        self,
        dialog: SettingsDialog | None,
        group: str,
        ok: bool,
        errors: FieldErrors,
        record: ProbeRecord | None,
    ) -> None:
        """接 Manager 结果，成功清标记，失败原地转向导"""
        if dialog is None or not self._owns(dialog, group):
            return
        self._busy = False
        self._pending_group = ""
        self._host._verify.validating = False
        self._host._verify.pending_aborts = None
        dialog.set_busy(False)
        if not ok:
            self._failed(dialog, group, errors)
            return
        if record is not None:
            self._host._probe.verified[group] = record
        dialog.source_saved(group, self._candidate)
        self._candidate = {}
        if self.wrote:
            self._pending_apply = True

    def cancelled(self) -> None:
        """中止在途保存并解锁，不挂失败标记"""
        self._busy = False
        self._pending_group = ""
        self._candidate = {}
        self._host._verify.validating = False
        self._host._verify.pending_aborts = None
        if self._host._panel is not None:
            self._host._panel.set_busy(False)

    def close(self) -> None:
        """关窗时中止后台保存"""
        if self._busy:
            self._host._verify.save_pending = True
            self._host._verify.abort_pending()
        self.cancelled()

    def _dispatch(
        self,
        dialog: SettingsDialog,
        group: str,
        candidate: AppConfigData,
        write: bool,
    ) -> None:
        """把本类候选与本场检测记录交 Manager"""
        self._candidate = candidate
        self.wrote = write
        self._host._verify.save_pending = True
        gui_bridge.config_source.emit(
            SourceSaveRequest(
                group=group,
                candidate=candidate,
                write=write,
                probes=dict(self._host._probe.verified),
            )
        )

    def _failed(self, dialog: SettingsDialog, group: str, errors: FieldErrors) -> None:
        """保存失败保留表单并原地转向导"""
        self._busy = False
        self._pending_group = ""
        self._candidate = {}
        self._host._verify.drop_pending()
        dialog.mark_source_failed(group, errors)

    def _owns(self, dialog: SettingsDialog, group: str) -> bool:
        """迟到结论只准收当前窗口的当前来源"""
        return (
            self._busy and self._pending_group == group and dialog is self._host._panel
        )

    def _remember_identity(self, changes: AppConfigData) -> None:
        """记录本类是否改过主人身份"""
        owner = owner_item()
        owner_section = (
            section_name(owner.source, owner.section) if owner is not None else ""
        )
        self.identity_changed = owner is not None and owner.key in (
            changes.get(owner_section) or {}
        )

    def log_changes(self, logs: list) -> None:
        """分级记录变更日志"""
        names = [name for name, _, _ in logs]
        joined = "、".join(names)
        self._host.logger.info(f"保存 {len(names)} 项配置: {joined}")
        if not logs:
            return
        detail = "".join(
            f"\n配置项：{key}\n原: {ori}\n新: {mod}" for key, ori, mod in logs
        )
        self._host.logger.debug(detail)
