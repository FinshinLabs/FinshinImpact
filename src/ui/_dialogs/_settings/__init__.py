"""配置向导

- 左侧大类与上排页签的两级表单、错误标红
- 变更确认窗由本包一并交出
"""

from copy import deepcopy
from enum import IntEnum, auto

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QFont, QKeyEvent, QShowEvent
from PySide6.QtWidgets import QWidget

from finshin_sdk.domain import ConnectionPlan
from skin.messages import DialogMessage
from skin.qss import build_error_label_qss, build_settings_dialog_qss
from skin.theme import SETTINGS_DIALOG
from utils.config import changed_groups, changed_sections, merge_source_config
from utils.config.models import (
    AppConfigData,
    AppSchema,
    FieldErrors,
    group_values,
    probe_of,
    tabs_by_group,
)
from utils.logger import get_logger

from ..._bridge import gui_bridge
from ..._primitives import BaseDialog
from .._notice import NoticeDialog
from ._change import ChangeConfirmDialog
from ._chrome import ChromeBuilder
from ._field import FieldBuilder, refresh_label
from ._source_button import SourceButtons

_ERROR_FONT = QFont(SETTINGS_DIALOG.error_font_family, SETTINGS_DIALOG.error_font_size)
_logger = get_logger("GUI.Settings")


def _sections_with_errors(schema: AppSchema, field_errors: FieldErrors) -> set[str]:
    """定位出错字段所在页"""
    return {
        tab.section
        for tab in schema
        if any(tab.path_of(f) in field_errors for f in tab.fields)
    }


class ConfigMode(IntEnum):
    """配置弹窗的工作模式"""

    EDIT = auto()  # 正常编辑（用户主动点击）
    SETUP = auto()  # 缺失引导（验证失败强制弹出）


class SettingsDialog(BaseDialog):
    """配置面板弹窗

    - 表单渲染与骨架装配各委托一只构建器
    - 磁盘快照、未存改动与未通过标记只活在本次开窗
    """

    save_requested = Signal(str)
    finish_requested = Signal()

    def __init__(
        self,
        schema: AppSchema,
        current_config: AppConfigData,
        mode: ConfigMode = ConfigMode.EDIT,
        parent: QWidget | None = None,
        field_errors: FieldErrors | None = None,
    ) -> None:
        super().__init__(parent=parent, title=SETTINGS_DIALOG.title)
        self._schema = schema
        self._groups = tabs_by_group(schema)
        self._mode = mode
        self._disk = deepcopy(current_config)
        self._dirty_groups: list[str] = []
        self._dirty_sections: list[str] = []
        self._warning_groups: set[str] = set()
        self._field_errors: FieldErrors = dict(field_errors or {})
        self._can_discard = False
        self.setStyleSheet(build_settings_dialog_qss())

        self._fields = FieldBuilder(current_config)
        self._actions = SourceButtons(self.save_requested.emit)
        self._chrome = ChromeBuilder(
            host=self,
            fields=self._fields,
            errors=self._field_errors,
            error_qss=build_error_label_qss(),
            error_font=_ERROR_FONT,
            on_exit=self._on_exit_clicked,
            on_save=self.finish_requested.emit,
            on_discard=self.discard_changes,
            actions=self._actions,
        )

        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowCloseButtonHint)
        self.setMinimumSize(SETTINGS_DIALOG.min_width, SETTINGS_DIALOG.min_height)
        self._chrome.build(
            schema,
            self._mode == ConfigMode.SETUP,
            self._can_discard,
            _sections_with_errors(schema, self._field_errors),
        )
        self._fields.watch(self.refresh_dirty)
        self.apply_errors(self._field_errors)
        self.refresh_dirty()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """向导态拦住关闭，编辑态先走完成判定"""
        event.ignore()
        if not self.is_setup:
            self.finish_requested.emit()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """显示后重估恢复钮与保存钮高度"""
        super().showEvent(event)
        self._fields.refresh_resets()
        self._actions.align()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """向导态吞掉 Esc，编辑态走完成判定"""
        if event.key() == Qt.Key.Key_Escape:
            event.accept()
            if not self.is_setup:
                self.finish_requested.emit()
            return
        super().keyPressEvent(event)

    def _on_exit_clicked(self) -> None:
        """退出程序，取消时保留本窗已填内容"""
        gui_bridge.request_exit.emit(self)

    @property
    def is_setup(self) -> bool:
        """当前是否向导态"""
        return self._mode == ConfigMode.SETUP

    @property
    def can_discard(self) -> bool:
        """盘上有好配置可回"""
        return self._can_discard

    @property
    def dirty_groups(self) -> list[str]:
        """相对磁盘仍有改动的大类"""
        return list(self._dirty_groups)

    @property
    def warning_groups(self) -> set[str]:
        """仍未检测通过的大类"""
        return set(self._warning_groups)

    def refresh_dirty(self) -> None:
        """重算未保存改动并刷新两级标题"""
        values = self.get_modified_config()
        self._dirty_groups = changed_groups(self._schema, self._disk, values)
        self._dirty_sections = changed_sections(self._schema, self._disk, values)
        self._refresh_marks()

    def disk_values(self) -> AppConfigData:
        """交本场磁盘快照"""
        return deepcopy(self._disk)

    def source_saved(self, group: str, candidate: AppConfigData) -> None:
        """保存成功后推进本类磁盘快照并清本类错误"""
        self._disk = merge_source_config(self._schema, self._disk, group, candidate)
        self._warning_groups.discard(group)
        remaining = {
            item: text
            for item, text in self._field_errors.items()
            if str(item.source) != group
        }
        self.apply_errors(remaining)
        self.refresh_dirty()
        if self.is_setup and not self._warning_groups:
            self.switch_to_edit()

    def restore_disk(self) -> None:
        """丢弃全部未存值，已挂的 ⚠ 保留"""
        self._fields.restore(self._schema, self._disk)
        self.refresh_dirty()

    def apply_errors(self, field_errors: FieldErrors | None) -> None:
        """原地刷新字段错误与两级标记"""
        self._field_errors = dict(field_errors or {})
        bad = _sections_with_errors(self._schema, self._field_errors)
        self._warning_groups.update(
            tab.group for tab in self._schema if tab.section in bad
        )
        for item, (label, title) in self._fields.labels.items():
            refresh_label(label, title, self._field_errors.get(item))
        self._chrome.set_error_marks(
            bad, self._dirty_groups, self._dirty_sections, self._warning_groups
        )
        self._fields.refresh_resets()

    def _refresh_marks(self) -> None:
        """同步字段错误所在页与未存、未通过标记"""
        self._chrome.set_error_marks(
            _sections_with_errors(self._schema, self._field_errors),
            self._dirty_groups,
            self._dirty_sections,
            self._warning_groups,
        )

    def set_busy(self, busy: bool) -> None:
        """保存或检测期间锁住表单防重入"""
        if self._chrome.save_btn is not None:
            self._chrome.save_btn.setEnabled(not busy)
            self._chrome.save_btn.setText(
                SETTINGS_DIALOG.validating_text if busy else SETTINGS_DIALOG.finish_text
            )
        self._chrome.lock_nav(busy)

    def switch_to_setup(self, field_errors: FieldErrors | None) -> None:
        """EDIT 原地转 SETUP，已填内容不丢"""
        self._mode = ConfigMode.SETUP
        self._can_discard = True
        self._field_errors = dict(field_errors or {})
        self._chrome.rebuild(True, self._can_discard)
        self.apply_errors(self._field_errors)

    def switch_to_edit(self) -> None:
        """SETUP 原地转 EDIT，已填内容不丢"""
        self._mode = ConfigMode.EDIT
        self._chrome.rebuild(False, self._can_discard)
        self.apply_errors(self._field_errors)

    def discard_changes(self) -> None:
        """回到盘上值并转回编辑态"""
        self.restore_disk()
        self._warning_groups.clear()
        self._field_errors.clear()
        self.switch_to_edit()
        _logger.debug("用户放弃未保存改动，配置回到盘上值")
        NoticeDialog.notify(DialogMessage.SETUP_DISCARDED, parent=self)

    def get_modified_config(self) -> AppConfigData:
        """从输入控件提取配置字典"""
        return self._fields.collect(self._schema)

    def probe_plan(
        self, group: str, data: AppConfigData | None = None
    ) -> ConnectionPlan | None:
        """按来源给定值造一份检测计划

        - 不给 data 即取表单值
        - 本来源没交检测件时交 None
        """
        tabs = self._groups.get(group) or []
        probe = probe_of(tabs)
        if probe is None:
            return None
        values = self.get_modified_config() if data is None else data
        return probe(group_values(tabs, values))

    def group_title(self, group: str) -> str:
        """本来源的大类标题"""
        tabs = self._groups.get(group) or []
        return tabs[0].group_title if tabs else group

    def apply_source_errors(self, group: str, field_errors: FieldErrors) -> None:
        """只刷本来源字段错误，别处标红不动"""
        merged = {
            item: text
            for item, text in self._field_errors.items()
            if str(item.source) != group
        }
        merged.update(field_errors)
        self.apply_errors(merged)

    def mark_source_failed(self, group: str, field_errors: FieldErrors) -> None:
        """失败挂 ⚠ 与字段红字，编辑态原地转向导"""
        self._warning_groups.add(group)
        self.apply_source_errors(group, field_errors)
        self.set_busy(False)
        if not self.is_setup:
            self.switch_to_setup(self._field_errors)
