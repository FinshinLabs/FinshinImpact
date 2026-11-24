"""插件行的搜索件

- 一只输入框配一档筛选，每敲一个字符当场筛一次
- 只切每行显隐，不动勾选也不动行序，清空即全显
- 一只都没命中时在列表下方顶一句提示
"""

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from finshin_sdk.dto import PluginManifestDTO
from skin.messages import PluginMessage

from .._primitives import ThemedList, make_combo

# 筛选档，决定比哪一列
_SCOPE_ALL = "all"
_SCOPE_NAME = "name"
_SCOPE_CMD = "cmd"

# 行上挂加载记录的数据角色
ROLE_MANIFEST = 0x0100

# 命令名的两种写法，面板上带斜杠显示，输入时带不带都要命中
_CMD_MARKS = ("", "/")


def _matches(manifest: PluginManifestDTO, query: str, scope: str) -> bool:
    """判这一行留不留

    - 不分大小写，子串命中即留
    - 名字一列比的是面板上看得见的显示名，没填标题即目录名
    """
    display = (manifest.declaration.title or manifest.name).lower()
    name_ok = scope != _SCOPE_CMD and query in display
    cmd_ok = scope != _SCOPE_NAME and any(query in one for one in _cmd_forms(manifest))
    return name_ok or cmd_ok


def _cmd_forms(manifest: PluginManifestDTO) -> list[str]:
    """交出每条命令名的带斜杠与不带斜杠两种写法"""
    return [
        f"{mark}{command.cmd}".lower()
        for section in manifest.declaration.help
        for command in section.commands
        for mark in _CMD_MARKS
    ]


class _PluginSearch(QWidget):
    """插件行搜索件

    - 输入框、筛选档与空命中提示三样
    """

    def __init__(self, rows: ThemedList) -> None:
        """接上要筛的加载记录

        - 行上的加载记录按列表项数据角色取
        - 记录由装配入口创建，本件只切每行的显隐
        """
        super().__init__()
        self._rows = rows
        self._edit = QLineEdit()
        self._edit.setPlaceholderText(PluginMessage.SEARCH_PLACEHOLDER)
        self._edit.setClearButtonEnabled(True)
        self._scope = make_combo(
            [
                (_SCOPE_ALL, PluginMessage.SEARCH_SCOPE_ALL),
                (_SCOPE_NAME, PluginMessage.SEARCH_SCOPE_NAME),
                (_SCOPE_CMD, PluginMessage.SEARCH_SCOPE_CMD),
            ]
        )
        self._tip = QLabel(PluginMessage.SEARCH_EMPTY)
        self._tip.setVisible(False)

        line = QHBoxLayout(self)
        line.addWidget(self._edit)
        line.addWidget(self._scope)
        self._edit.textChanged.connect(self.refresh)
        self._scope.currentIndexChanged.connect(self.refresh)

    def mount(self, layout: QVBoxLayout) -> None:
        """挂上搜索行与空命中提示

        - 搜索行插到清单上方
        - 空命中提示接到清单下方
        """
        index = layout.indexOf(self._rows)
        layout.insertWidget(index, self)
        layout.insertWidget(index + 2, self._tip)

    def refresh(self) -> None:
        """按输入串与档位切每行显隐

        - 空串即整表恢复显示，勾选态本就没动过
        - 隐藏行仍算在启用集里，保存按整张表提交
        - 行上挂的控件跟着行一起隐
        """
        query = self._edit.text().strip().lower()
        scope = self._scope.currentData()
        hits = 0
        for index in range(self._rows.count()):
            item = self._rows.item(index)
            keep = not query or _matches(item.data(ROLE_MANIFEST), query, scope)
            item.setHidden(not keep)
            widget = self._rows.itemWidget(item)
            if widget is not None:
                widget.setHidden(not keep)
            hits += int(keep)
        self._tip.setVisible(hits == 0)


def build_searchable_list(layout: QVBoxLayout) -> tuple[ThemedList, _PluginSearch]:
    """装配插件列表与搜索件

    - 交出记录列表与搜索件
    - 列表、搜索行与空命中提示按这个顺序进布局
    - 行内容仍由调用方填，重拼行之后要叫搜索件补筛一次
    """
    rows = ThemedList()
    layout.addWidget(rows)
    search = _PluginSearch(rows)
    search.mount(layout)
    return rows, search
