"""页签条来源保存钮

- 每个左侧大类在页签条右端都有同一颗保存钮
- 钮只报来源身份，保存流程交控制器
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QTabWidget

from skin.theme import SETTINGS_DIALOG, ButtonSize, ButtonStyle

from ..._primitives import make_button


class SourceButtons:
    """各来源的保存钮

    - 按来源身份留钮引用，统一开关
    - 显示后按各自页签条高度钉齐
    """

    def __init__(self, on_save: Callable[[str], None]) -> None:
        self._on_save = on_save
        self._mounted: dict[str, tuple[QPushButton, QTabWidget]] = {}

    def mount(self, group_tabs: QTabWidget, group: str) -> None:
        """把本大类的保存钮挂到页签条右端"""
        button = make_button(
            SETTINGS_DIALOG.save_source_text,
            ButtonStyle.PRIMARY,
            size=ButtonSize.SMALL,
            on_click=lambda: self._on_save(group),
        )
        group_tabs.setCornerWidget(button, Qt.Corner.TopRightCorner)
        self._mounted[group] = (button, group_tabs)

    def align(self) -> None:
        """保存钮钉成页签条高度

        - 须在显示之后再钉，样式表铺开时会用 min-height 把固定高顶回去
        """
        for button, group_tabs in self._mounted.values():
            button.setFixedHeight(group_tabs.tabBar().sizeHint().height())

    def set_enabled(self, enabled: bool) -> None:
        """统一开关各来源保存钮"""
        for button, _ in self._mounted.values():
            button.setEnabled(enabled)
