"""主题门面

- 汇总调色板、核心、弹窗与引导令牌并实例化
- 导出全局单例
"""

from ._buttons import ButtonSize, ButtonStyle, button_object_name
from ._dialogs import (
    ChangeDialogTheme,
    CheckDialogTheme,
    FiveStateDialogTheme,
    LinkDialogTheme,
    NoticeDialogTheme,
    PlatformDialogTheme,
    ReleaseNotesDialogTheme,
    ShutdownDialogTheme,
    WaitDialogTheme,
)
from ._global import (
    BodyTheme,
    FontTheme,
    GlobalTheme,
    ScrollbarTheme,
    ToolbarTheme,
    WindowTheme,
)
from ._guide import (
    FormTheme,
    GuideFieldTheme,
    LaunchTheme,
    PanelTheme,
    PickerTheme,
)
from ._names import ObjectName
from ._palette import PALETTE
from ._settings import SettingsDialogTheme, SettingsListTheme

# 核心令牌
WINDOW = WindowTheme()
FONT = FontTheme()
GLOBAL = GlobalTheme()
BODY = BodyTheme()
TOOLBAR = ToolbarTheme()
SCROLLBAR = ScrollbarTheme()

# 弹窗令牌
SETTINGS_DIALOG = SettingsDialogTheme()
LIST_DIALOG = SettingsListTheme()
SHUTDOWN_DIALOG = ShutdownDialogTheme()
CHANGE_DIALOG = ChangeDialogTheme()
CHECK_DIALOG = CheckDialogTheme()
WAIT_DIALOG = WaitDialogTheme()
NOTICE_DIALOG = NoticeDialogTheme()
PLATFORM_DIALOG = PlatformDialogTheme()
RELEASE_NOTES_DIALOG = ReleaseNotesDialogTheme()
LINK_DIALOG = LinkDialogTheme()

# 引导令牌
PICKER = PickerTheme()
FORM = FormTheme()
PANEL = PanelTheme()
GUIDE_FIELD = GuideFieldTheme()
LAUNCH = LaunchTheme()
