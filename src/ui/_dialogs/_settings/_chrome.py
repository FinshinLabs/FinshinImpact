"""骨架装配

- 构建根布局、左侧大类列表、上排页签与底排的提示和按钮条
- 承载 EDIT 与 SETUP 两模式的原地拆装
"""

from collections.abc import Callable

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from finshin_sdk.domain.config import ConfigPath
from skin.theme import GLOBAL, SETTINGS_DIALOG, ButtonStyle, ObjectName
from utils.config import owner_field
from utils.config.models import AppSchema, FieldErrors, TabSchema, tabs_by_group

from ..._primitives import (
    ButtonBar,
    ButtonSpec,
    clear_layout,
    make_scroller,
)
from .._persona import PersonaPreviewRow
from ._field import FieldBuilder
from ._source_button import SourceButtons

_DIRTY_MARK = "✏️"
_WARNING_MARK = "⚠"


class ChromeBuilder:
    """骨架装配器

    - 持有根布局、大类导航、按钮条引用，供弹窗跨模式续用
    - 页签标题与大类文案左挂出错标记，右挂未存改动标记
    - 每个来源在页签条右端挂一颗保存钮
    """

    def __init__(
        self,
        host: QWidget,
        fields: FieldBuilder,
        errors: FieldErrors,
        error_qss: str,
        error_font: QFont,
        on_exit: Callable[[], None],
        on_save: Callable[[], None],
        on_discard: Callable[[], None],
        actions: SourceButtons,
    ) -> None:
        self._host = host
        self._fields = fields
        self._errors = errors
        self._error_qss = error_qss
        self._error_font = error_font
        self._on_exit = on_exit
        self._on_save = on_save
        self._on_discard = on_discard
        self._actions = actions

        # 根布局/按钮条引用：原地切模式只拆可再生部件，表单永不重建
        self.root_layout: QVBoxLayout | None = None
        self.bottom_layout: QHBoxLayout | None = None

        # 导航引用：复验结果原地刷新用（免关窗重开的闪烁）
        # 页段 -> (大类, 页签序号, 无标记标题)，大类 -> (列表项, 无标记文案)
        self._group_tabs: dict[str, QTabWidget] = {}
        self._tab_refs: dict[str, tuple[str, int, str]] = {}
        self._category_items: dict[str, tuple[QListWidgetItem, str]] = {}
        self.dirty_groups: list[str] = []
        self.dirty_sections: list[str] = []
        self.warning_groups: set[str] = set()
        self._categories = QListWidget()
        self._pages = QStackedWidget()
        self.save_btn: QPushButton | None = None

    def build(
        self,
        schema: AppSchema,
        is_setup: bool,
        can_discard: bool,
        error_sections: set[str],
    ) -> None:
        """构建界面"""
        root_layout = QVBoxLayout(self._host)
        self.root_layout = root_layout
        root_layout.setContentsMargins(
            *([SETTINGS_DIALOG.input_padding_h, SETTINGS_DIALOG.input_padding_v] * 2)
        )
        root_layout.setSpacing(SETTINGS_DIALOG.tab_spacing)

        root_layout.addLayout(self._build_nav(schema), stretch=1)
        self.set_error_marks(error_sections, [], [], set())
        self.bottom_layout = self._build_bottom_buttons(is_setup, can_discard)
        root_layout.addLayout(self.bottom_layout)

    def rebuild(self, is_setup: bool, can_discard: bool) -> None:
        """拆建底排提示与按钮条"""
        if self.root_layout is None:
            return
        if self.bottom_layout is not None:
            self.root_layout.removeItem(self.bottom_layout)
            clear_layout(self.bottom_layout)
        self.bottom_layout = self._build_bottom_buttons(is_setup, can_discard)
        self.set_error_marks(
            set(), self.dirty_groups, self.dirty_sections, self.warning_groups
        )
        self.root_layout.addLayout(self.bottom_layout)

    def _build_nav(self, schema: AppSchema) -> QHBoxLayout:
        """装配左侧大类与右侧上排页签

        - 段按来源顺序归组，大类首次出现即定列表行序
        - 一个大类一本页签，切大类只换堆叠页，已填内容不重建
        """
        self._categories.setObjectName(ObjectName.CATEGORY_LIST)
        self._categories.setFixedWidth(SETTINGS_DIALOG.category_width)

        for group, tabs in tabs_by_group(schema).items():
            title = tabs[0].group_title
            item = QListWidgetItem(title)
            self._categories.addItem(item)
            self._category_items[group] = (item, title)

            group_tabs = QTabWidget()
            for index, tab in enumerate(tabs):
                group_tabs.addTab(self._create_tab(tab), tab.title)
                self._tab_refs[tab.section] = (group, index, tab.title)
            self._actions.mount(group_tabs, group)
            self._group_tabs[group] = group_tabs
            self._pages.addWidget(group_tabs)

        self._categories.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._categories.setCurrentRow(0)

        nav = QHBoxLayout()
        nav.setSpacing(SETTINGS_DIALOG.category_spacing)
        nav.addWidget(self._categories)
        nav.addWidget(self._pages, stretch=1)
        return nav

    def set_error_marks(
        self,
        error_sections: set[str],
        dirty_groups: list[str],
        dirty_sections: list[str],
        warning_groups: set[str],
    ) -> None:
        """按出错段、未存页签与未存大类增撤标记

        - 出错标记在左，未存改动标记在右，只换标题文字，控件与已填内容不动
        """
        bad_groups: set[str] = set()
        self.dirty_groups = list(dirty_groups)
        self.dirty_sections = list(dirty_sections)
        self.warning_groups = set(warning_groups)
        dirty = set(dirty_groups)
        for section, (group, index, title) in self._tab_refs.items():
            warning = f"{_WARNING_MARK} " if section in error_sections else ""
            changed = f" {_DIRTY_MARK}" if section in self.dirty_sections else ""
            if section in error_sections:
                bad_groups.add(group)
            self._group_tabs[group].setTabText(index, f"{warning}{title}{changed}")
        for group, (item, title) in self._category_items.items():
            warning = (
                f"{_WARNING_MARK} "
                if group in bad_groups or group in warning_groups
                else ""
            )
            changed = f" {_DIRTY_MARK}" if group in dirty else ""
            item.setText(f"{warning}{title}{changed}")

    def lock_nav(self, locked: bool) -> None:
        """锁住两级导航与保存钮"""
        self._categories.setEnabled(not locked)
        for group_tabs in self._group_tabs.values():
            group_tabs.setEnabled(not locked)
        self._actions.set_enabled(not locked)

    def _make_tip(self) -> QLabel:
        """构造 SETUP 模式的提示行

        - 向导只会带着字段级错误开窗，提示恒指 ⚠ 页签
        """
        tip_label = QLabel(SETTINGS_DIALOG.setup_tip)
        tip_label.setStyleSheet(self._error_qss)
        tip_label.setFont(self._error_font)
        return tip_label

    def _create_tab(self, tab_schema: TabSchema) -> QWidget:
        """创建一个 Tab"""
        container = QWidget()
        container.setObjectName(ObjectName.TAB_CONTAINER)
        main_layout = QVBoxLayout(container)
        main_layout.setSpacing(SETTINGS_DIALOG.tab_spacing)
        rows: dict[ConfigPath, QWidget] = {}
        for field in tab_schema.fields:
            row = self._fields.build(tab_schema, field, self._errors)
            rows[tab_schema.path_of(field)] = row
            main_layout.addWidget(row)
        self._mount_persona_row(tab_schema, main_layout)
        self._mount_field_visibility(tab_schema, rows)
        main_layout.addStretch()
        scroll = make_scroller(container)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setAutoFillBackground(False)
        return scroll

    def _mount_field_visibility(
        self, tab: TabSchema, rows: dict[ConfigPath, QWidget]
    ) -> None:
        """字段按同段其他字段的取值显隐

        - 条件全部命中才显示整行，值保留在控件里切回即现
        - 依赖的控件不是下拉即不接线
        """
        controllers = {cond.key for field in tab.fields for cond in field.visible_when}
        for key in controllers:
            controller = next((f for f in tab.fields if f.key == key), None)
            if controller is None:
                continue
            combo = self._fields.inputs.get(tab.path_of(controller))
            if not isinstance(combo, QComboBox):
                continue

            def sync(_index: int = -1) -> None:
                current = {
                    field.key: self._fields.value_of(tab.path_of(field), field)
                    for field in tab.fields
                }
                for field in tab.fields:
                    if not field.visible_when:
                        continue
                    row = rows.get(tab.path_of(field))
                    if row is None:
                        continue
                    row.setVisible(
                        all(
                            str(current.get(cond.key)) in cond.values
                            for cond in field.visible_when
                        )
                    )

                # 切换即重估全部恢复钮，否则按钮显隐停在开窗时的旧值
                self._fields.refresh_resets()

            combo.currentIndexChanged.connect(sync)
            sync()

    def _mount_persona_row(self, tab: TabSchema, layout: QVBoxLayout) -> None:
        """人设入口行挂载

        - 本页取不到主人输入控件即不挂载
        """
        owner = owner_field(tab.fields)
        if owner is None:
            return
        owner_input = self._fields.inputs.get(tab.path_of(owner))
        if owner_input is None:
            return

        row = PersonaPreviewRow()
        if not row.bind(owner_input):
            return
        layout.addWidget(row)

    def _build_bottom_buttons(self, is_setup: bool, can_discard: bool) -> QHBoxLayout:
        """按模式构建底部按钮"""
        # 发信号而非 accept：校验通过才关窗，失败则原窗保留已填内容
        if is_setup:
            specs = []
            if can_discard:
                specs.append(
                    ButtonSpec(
                        SETTINGS_DIALOG.discard_text,
                        ButtonStyle.OUTLINE,
                        on_click=self._on_discard,
                    )
                )
            specs.append(
                ButtonSpec(
                    SETTINGS_DIALOG.exit_text,
                    ButtonStyle.OUTLINE,
                    on_click=self._on_exit,
                )
            )
        else:
            specs = [
                ButtonSpec(
                    SETTINGS_DIALOG.finish_text,
                    ButtonStyle.PRIMARY,
                    on_click=self._on_save,
                )
            ]

        bar = ButtonBar(specs, self._host, spacing=GLOBAL.radius)
        self.save_btn = None if is_setup else bar.buttons[0]
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        if is_setup:
            btn_layout.addWidget(self._make_tip())
        btn_layout.addWidget(bar, 1)
        return btn_layout
