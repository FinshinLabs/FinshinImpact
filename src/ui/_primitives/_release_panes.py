"""版本清单与正文两栏

- 左清单逐版一行、各行等高，右栏摆选中那版的正文
- 选中行一变即换正文并交出行号
"""

from collections.abc import Sequence
from dataclasses import dataclass

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from skin.theme import PALETTE, RELEASE_NOTES_DIALOG, ObjectName

from ._list import ThemedList


@dataclass(frozen=True, slots=True)
class PaneEntry:
    """清单里的一行

    - label 是屏上那一行字，body 是选中后右侧的正文
    - dimmed 为真的行按置灰字色出
    """

    label: str
    body: str
    dimmed: bool = False


class ReleasePanes(QWidget):
    """左清单配右正文

    - 正文链接交系统浏览器接手
    """

    current_changed = Signal(int)

    def __init__(
        self,
        entries: Sequence[PaneEntry],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._bodies = tuple(entry.body for entry in entries)
        self._listing = ThemedList(parent=self)
        self._listing.setObjectName(ObjectName.LIST_WIDGET)
        self._listing.setFixedWidth(RELEASE_NOTES_DIALOG.list_width)
        dim = QBrush(QColor(PALETTE.disabled_color))
        for entry in entries:
            item = QListWidgetItem(entry.label)
            if entry.dimmed:
                item.setForeground(dim)
            self._listing.addItem(item)
        self._equalize_rows()
        self._listing.currentRowChanged.connect(self._show)

        # QTextEdit 没有链接信号，只读视图要用 QTextBrowser
        self._view = QTextBrowser(parent=self)
        self._view.setObjectName(ObjectName.RELEASE_NOTES_VIEW)
        self._view.setOpenExternalLinks(True)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(RELEASE_NOTES_DIALOG.spacing)
        side.addWidget(self._view, 1)

        panes = QHBoxLayout(self)
        panes.addWidget(self._listing)
        panes.addLayout(side, 1)

        self._listing.setCurrentRow(0 if entries else -1)

    def _equalize_rows(self) -> None:
        """各行按最高那一行取齐，免得一格高一格低"""
        heights = [
            self._listing.sizeHintForRow(index)
            for index in range(self._listing.count())
        ]
        for index in range(self._listing.count()):
            item = self._listing.item(index)
            if item is not None:
                item.setSizeHint(QSize(0, max(heights)))

    def current_row(self) -> int:
        """当前选中的行号，无选中交出 -1"""
        return self._listing.currentRow()

    def set_current_row(self, row: int) -> None:
        """按行号选中，越界按无选中处理"""
        self._listing.setCurrentRow(row if 0 <= row < len(self._bodies) else -1)

    def _show(self, row: int) -> None:
        self._view.setMarkdown(self._bodies[row] if row >= 0 else "")
        self.current_changed.emit(row)
