"""版本变化弹窗

- 左列版本清单配右侧正文
"""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from services.release_feed import ReleaseNote
from skin.qss import build_release_notes_dialog_qss
from skin.theme import RELEASE_NOTES_DIALOG, ButtonStyle

from .._primitives import (
    BaseDialog,
    PaneEntry,
    ReleasePanes,
    make_button,
    set_margins,
)

# 无选中行时的行号
_NO_ROW = -1


class ReleaseNotesDialog(BaseDialog):
    """版本变化弹窗"""

    def __init__(
        self,
        notes: Sequence[ReleaseNote],
        focus_tag: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent, title=RELEASE_NOTES_DIALOG.title)
        self.setStyleSheet(build_release_notes_dialog_qss())

        layout = QVBoxLayout(self)
        set_margins(layout, RELEASE_NOTES_DIALOG.pad)
        layout.setSpacing(RELEASE_NOTES_DIALOG.spacing)

        entries = tuple(PaneEntry(note.tag, note.body) for note in notes)
        self._panes = ReleasePanes(entries, self)
        layout.addWidget(self._panes, 1)
        btn = make_button(
            RELEASE_NOTES_DIALOG.ok_text, ButtonStyle.PRIMARY, default=True
        )
        btn.clicked.connect(self.accept)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # 尺寸定死：正文再长也不把窗口顶出屏幕，读不完的部分交给滚动
        self.setFixedSize(RELEASE_NOTES_DIALOG.width, RELEASE_NOTES_DIALOG.height)

        # 未命中焦点版本即落回最新一版，空清单留无选中
        row = _NO_ROW
        if notes:
            row = next((i for i, note in enumerate(notes) if note.tag == focus_tag), 0)
        self._panes.set_current_row(row)

    @staticmethod
    def show_release_notes(
        notes: Sequence[ReleaseNote],
        focus_tag: str = "",
        parent: QWidget | None = None,
    ) -> None:
        """模态展示各版本发布说明"""
        ReleaseNotesDialog(notes, focus_tag, parent=parent).exec()
