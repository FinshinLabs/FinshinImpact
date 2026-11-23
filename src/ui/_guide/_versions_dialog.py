"""平台组件的「其他版本」窗

- 左清单逐版标本机状态，右栏直接摆那一版的正文
- 取数中底部不出按钮，取回或取不到才出
- 装不装得由面板同一条判据现算，挡住的版按钮改「不可安装」并置灰
- 装完交回面板按最新读数重灌
"""

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from services.env_setup.platform_rows import ComponentRow
from services.env_setup.platform_state import (
    VersionEntry,
    VersionState,
    version_entries,
)
from services.release_feed import ReleaseNote, version_of_tag
from skin.messages import DialogMessage, PlatformMessage
from skin.qss import build_release_notes_dialog_qss
from skin.theme import RELEASE_NOTES_DIALOG, ButtonStyle

from .._primitives import (
    BaseDialog,
    PaneEntry,
    ReleasePanes,
    clear_layout,
    make_button,
    set_margins,
)
from ._platform_flow import install_flow
from ._platform_text import row_note, version_state_text
from ._versions_task import VersionsTask

# 关窗时仍在跑的取数线程，跑完自摘
_RUNNING: set[VersionsTask] = set()


class VersionsDialog(BaseDialog):
    """一只组件的「其他版本」窗

    - 开窗即后台取这只仓的正式 release
    - 底部安装那颗跟着选中版能不能装走
    """

    def __init__(
        self,
        parent: QWidget | None,
        row: ComponentRow,
        rows: Sequence[ComponentRow],
        on_done: Callable[[], None],
    ) -> None:
        super().__init__(parent=parent, title=PlatformMessage.VERSIONS_TITLE)
        self.setStyleSheet(build_release_notes_dialog_qss())
        self._row = row
        self._rows = rows
        self._on_done = on_done
        self._entries: tuple[VersionEntry, ...] = ()
        self._blocked: list[str] = []
        self._panes: ReleasePanes | None = None

        layout = QVBoxLayout(self)
        set_margins(layout, RELEASE_NOTES_DIALOG.pad)
        layout.setSpacing(RELEASE_NOTES_DIALOG.spacing)
        self._content = QVBoxLayout()
        layout.addLayout(self._content, 1)
        self._content.addWidget(QLabel(PlatformMessage.WAIT_VERSIONS, parent=self))

        self._foot = QWidget(self)
        foot = QHBoxLayout(self._foot)
        foot.setContentsMargins(0, 0, 0, 0)
        close = make_button(DialogMessage.BTN_CLOSE, ButtonStyle.OUTLINE)
        close.clicked.connect(self.reject)
        self._install = make_button(
            PlatformMessage.BTN_INSTALL_THIS, ButtonStyle.PRIMARY
        )
        self._install.setEnabled(False)
        self._install.clicked.connect(self._install_current)
        foot.addStretch()
        foot.addWidget(close)
        foot.addWidget(self._install)
        foot.addStretch()
        self._foot.hide()
        layout.addWidget(self._foot, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setFixedSize(RELEASE_NOTES_DIALOG.width, RELEASE_NOTES_DIALOG.height)

        url = row.release.url if row.release is not None else ""
        self._task = VersionsTask(url)
        self._task.reported.connect(self._on_reported)
        self._task.start()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """关窗时取数未回则把线程交给模块级集合持有"""
        if self._task.isRunning():
            task = self._task
            _RUNNING.add(task)
            task.finished.connect(lambda: _RUNNING.discard(task))
        super().closeEvent(event)

    def _on_reported(self, notes: object, reason: str) -> None:
        """取数回来后摆清单或那行原因"""
        clear_layout(self._content)
        self._foot.show()
        if not isinstance(notes, tuple):
            self._install.setEnabled(False)
            self._install.setText(PlatformMessage.BTN_CANNOT_INSTALL)
            self._content.addWidget(QLabel(reason, parent=self))
            return

        self._build(notes)

    def _build(self, notes: Sequence[ReleaseNote]) -> None:
        """按目录版本清单与取回的正文摆两栏

        - 正文按版本号对回那一版
        - 已装与挡住的几版同一种灰态
        """
        bodies = {version_of_tag(note.tag): note.body for note in notes}
        self._entries = version_entries(self._row)
        self._blocked = [
            row_note(self._rows, self._row, entry.release) if self._row.platform else ""
            for entry in self._entries
        ]
        panes = tuple(
            PaneEntry(
                label=f"{entry.release.version}  {version_state_text(entry)}",
                body=bodies.get(entry.release.version, ""),
                dimmed=entry.state == VersionState.CURRENT or bool(blocked),
            )
            for entry, blocked in zip(self._entries, self._blocked, strict=True)
        )
        self._panes = ReleasePanes(panes, self)
        self._panes.current_changed.connect(self._select)
        self._content.addWidget(self._panes, 1)
        self._select(self._panes.current_row())

    def _select(self, row: int) -> None:
        """按选中行定底部那颗的字与可用态"""
        if not 0 <= row < len(self._entries):
            self._install.setEnabled(False)
            self._install.setText(PlatformMessage.BTN_CANNOT_INSTALL)
            return

        entry = self._entries[row]
        disabled = entry.state == VersionState.CURRENT or bool(self._blocked[row])
        self._install.setEnabled(not disabled)
        self._install.setText(
            PlatformMessage.BTN_CANNOT_INSTALL
            if disabled
            else PlatformMessage.BTN_INSTALL_THIS
        )

    def _install_current(self) -> None:
        """装当前选中那一版"""
        row = self._panes.current_row() if self._panes is not None else -1
        if not 0 <= row < len(self._entries):
            return

        if not self._install.isEnabled():
            return
        install_flow(self._installed, [self._entries[row].release])

    def _installed(self) -> None:
        """装完收起本窗并交回面板重灌"""
        self.accept()
        self._on_done()
