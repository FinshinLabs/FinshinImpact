"""平台组件面板的组件块

- 适配器一块，块内按来源、来路、版本、接口包要求与动作逐行摆
- 接口包一块只出名字与版本读数
- 每只适配器一颗「其他版本」，点开另起一只窗看全部版本
- 动作栏只摆做得到的动作，置灰那颗旁边跟一句下一步
"""

from collections.abc import Callable, Sequence

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from finshin_sdk.domain.ids import PlatformCode
from services.adapter_catalog import ReleaseRow
from services.env_setup.platform_rows import (
    ComponentBucket,
    ComponentRow,
    ComponentSource,
)
from services.env_setup.platform_state import (
    deps_text,
    source_origin,
    update_target,
)
from skin.messages import PlatformMessage
from skin.theme import PLATFORM_DIALOG, ButtonSize, ButtonStyle, ObjectName

from .._primitives import clear_layout, make_button, set_margins
from ._platform_flow import install_flow, uninstall_flow
from ._platform_text import (
    action_text,
    name_text,
    origin_text,
    row_note,
    source_text,
    version_text,
)
from ._versions_dialog import VersionsDialog


class ComponentBlock(QFrame):
    """一只组件一块

    - 接口包那块只出名字与版本读数，没有动作可点
    - 装卸跑完面板整片重灌，块跟着按新读数重建
    """

    def __init__(
        self,
        host: QWidget,
        row: ComponentRow,
        rows: Sequence[ComponentRow],
        on_done: Callable[[], None],
    ) -> None:
        super().__init__(host)
        self._row = row
        self._rows = rows
        self._on_done = on_done
        self._target = update_target(rows, row)
        self._note = row_note(rows, row, self._target)
        self.setObjectName(ObjectName.PLATFORM_BLOCK)
        self._lines = QVBoxLayout(self)
        set_margins(self._lines, PLATFORM_DIALOG.block_pad)
        self._rebuild()

    def _rebuild(self) -> None:
        """按这一行的读数重摆块内的行

        - 接口包那块摆完名字与版本读数即收
        - 来路那一行只在本机有得取的内容时出，点名取的是哪一版
        """
        clear_layout(self._lines)
        head = QLabel(name_text(self._row), parent=self)
        head.setObjectName(ObjectName.PLATFORM_NAME)
        self._lines.addWidget(head)
        if not self._row.platform:
            self._add_text(
                f"{PlatformMessage.LABEL_VERSION}：{version_text(self._row)}"
            )
            return

        self._add_text(f"{PlatformMessage.LABEL_SOURCE}：{source_text(self._row)}")
        version = self._target.version if self._target is not None else ""
        origin = origin_text(source_origin(self._rows, self._row), version)
        if origin:
            self._add_text(f"{PlatformMessage.LABEL_ORIGIN}：{origin}")
        self._add_text(f"{PlatformMessage.LABEL_VERSION}：{version_text(self._row)}")

        requires = deps_text(self._row)
        if requires:
            self._add_text(f"{PlatformMessage.LABEL_DEPS}：{requires}")
        self._add_actions()

    def _add_actions(self) -> None:
        """动作栏按钮

        - 只摆做得到的动作
        - 更新或安装那颗只在有得装时出，置灰时旁边跟一句下一步
        - 已装包的多一颗卸载，有目录行的多一颗「其他版本」
        - 一颗都没有即整行不出
        """
        installable = (
            self._row.release is not None and self._row.bucket != ComponentBucket.LOCAL
        )
        buttons: list[QPushButton] = []
        if installable:
            buttons.append(
                self._install_button(self._target, action_text(self._row), self._note)
            )
        if bool(self._row.platform) and self._row.source == ComponentSource.INSTALLED:
            buttons.append(self._uninstall_button())
        if self._row.release is not None:
            buttons.append(self._versions_button())
        if not buttons:
            return

        holder = QWidget(parent=self)
        pair = QHBoxLayout(holder)
        pair.setContentsMargins(0, 0, 0, 0)
        for button in buttons:
            pair.addWidget(button)
        if installable and self._note:
            pair.addWidget(QLabel(self._note, parent=holder))
        pair.addStretch()
        self._add_pair(f"{PlatformMessage.LABEL_ACTION}：", holder)

    def _versions_button(self) -> QPushButton:
        """打开这只组件「其他版本」窗的那一颗"""
        button = make_button(
            PlatformMessage.BTN_OTHER_VERSIONS,
            ButtonStyle.OUTLINE,
            size=ButtonSize.SMALL,
        )
        button.clicked.connect(
            lambda: VersionsDialog(
                self.window(), self._row, self._rows, self._on_done
            ).exec()
        )

        return button

    def _install_button(
        self, release: ReleaseRow | None, text: str, blocked: str
    ) -> QPushButton:
        """装这一版的按钮

        - 挡住即置灰，没有这一版即不接动作
        """
        button = make_button(text, ButtonStyle.PRIMARY)
        button.setEnabled(release is not None and not blocked)
        if release is not None:
            button.clicked.connect(lambda: install_flow(self._on_done, [release]))

        return button

    def _uninstall_button(self) -> QPushButton:
        """卸掉这只适配器的那颗"""
        button = make_button(PlatformMessage.BTN_UNINSTALL, ButtonStyle.DANGER)
        button.clicked.connect(
            lambda: uninstall_flow(
                self.window(), self._on_done, PlatformCode(self._row.platform)
            )
        )

        return button

    def _add_text(self, text: str) -> None:
        """整行只有一句文本"""
        self._lines.addWidget(QLabel(text, parent=self))

    def _add_pair(self, text: str, value: QWidget) -> None:
        """一行文本后面跟一只控件"""
        holder = QWidget(parent=self)
        pair = QHBoxLayout(holder)
        pair.setContentsMargins(0, 0, 0, 0)
        pair.addWidget(QLabel(text, parent=holder))
        pair.addWidget(value)
        pair.addStretch()
        self._lines.addWidget(holder)
