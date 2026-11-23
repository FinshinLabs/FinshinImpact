"""实例表单窗

- 收凭证与备注名，新建与编辑共用同一表单
- 凭证的名字与提示按平台声明取
"""

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from finshin_sdk import CredentialSpec
from finshin_sdk.domain import PlatformCode, ProfileKey, platform_of_key
from services.adapter_credential import credential_of
from services.env_setup.platform_rows import present_platforms
from services.profile_store import create_profile, update_profile
from skin.messages import PickerMessage, PluginMessage
from skin.qss import build_bootstrap_qss
from skin.theme import FORM, ButtonStyle
from system.profile_env import read_token

from .._primitives import BaseDialog, fill_combo, make_button, make_combo
from ._platform import open_platform_dialog
from ._popup import show_popup


def _platform_items() -> list[tuple[PlatformCode, str]]:
    """本机装着适配器包的平台下拉项

    - 按平台码升序
    """
    return [
        (PlatformCode(code), PickerMessage.PLATFORM_NAMES.get(code, code))
        for code in sorted(present_platforms())
    ]


class _ProfileFormDialog(BaseDialog):
    """实例表单窗

    - 收凭证与备注名，凭证块内字段名与提示由声明填
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent, title=title)
        self.code = ""
        self._spec: CredentialSpec | None = None
        self._build()

    def _build(self) -> None:
        """装配控件"""
        self.setStyleSheet(build_bootstrap_qss())
        self.resize(FORM.width, FORM.height)
        self.setMinimumSize(FORM.min_width, FORM.min_height)

        form = QVBoxLayout(self)

        self._build_head(form)
        self._build_credential(form)

        form.addStretch()

        buttons = QHBoxLayout()
        ok = make_button(PickerMessage.BTN_OK, ButtonStyle.PRIMARY, default=True)
        ok.clicked.connect(self._on_ok)
        buttons.addStretch()
        buttons.addWidget(ok)
        form.addLayout(buttons)

    def _build_head(self, form: QVBoxLayout) -> None:
        """表单顶部扩展位"""

    def _build_credential(self, form: QVBoxLayout) -> None:
        """装配凭证与备注块

        - 字段名与提示留空，等声明到场再填
        """
        self._credential_box = QWidget()
        box = QVBoxLayout(self._credential_box)
        box.setContentsMargins(0, 0, 0, 0)

        self._credential_label = QLabel()
        box.addWidget(self._credential_label)

        self._credential = QLineEdit()
        box.addWidget(self._credential)

        # 提示常显于输入框外，避免输入后被占位符遮住看不见
        self._credential_hint = QLabel()
        self._credential_hint.setWordWrap(True)
        box.addWidget(self._credential_hint)

        box.addWidget(QLabel(PickerMessage.FORM_REMARK_LABEL))
        self._remark = QLineEdit()
        box.addWidget(self._remark)

        form.addWidget(self._credential_box)

    def _apply_credential(self, spec: CredentialSpec) -> None:
        """按声明摆出凭证块"""
        self._spec = spec
        self._credential_label.setText(spec.label)
        self._credential_hint.setText(spec.desc)
        self._credential_box.setVisible(True)

    def _hide_credential(self) -> None:
        """收起凭证块并清掉声明"""
        self._spec = None
        self._credential_box.setVisible(False)

    def _on_ok(self) -> None:
        """校验凭证并落盘

        - 由子类实现
        """
        raise NotImplementedError

    def _warn(self, body: str) -> None:
        """表单内警告弹窗"""
        show_popup(self.windowTitle(), body, parent=self)


class NewProfileDialog(_ProfileFormDialog):
    """新建实例窗

    - 先选平台，再按该平台的凭证声明填串
    - 身份码由声明里的推导给出
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        self._chosen: PlatformCode | None = None
        super().__init__(PickerMessage.NEW_TITLE, parent)
        self._hide_credential()
        self._platform.currentIndexChanged.connect(self._on_platform_changed)

    def _build_head(self, form: QVBoxLayout) -> None:
        """装配平台下拉与平台组件入口

        - 下拉只列本机装着适配器包的平台，开窗时不选中第一项
        """
        form.addWidget(QLabel(PickerMessage.NEW_PLATFORM_LABEL))
        self._platform = make_combo(_platform_items())
        self._platform.setPlaceholderText(PickerMessage.NEW_PLATFORM_PLACEHOLDER)
        self._platform.setCurrentIndex(-1)

        # 入口那颗与下拉同排，不占下拉的一项
        head = QHBoxLayout()
        head.addWidget(self._platform, 1)
        manage = make_button(PluginMessage.MENU_PLATFORM, ButtonStyle.OUTLINE)
        manage.setAutoDefault(False)
        manage.clicked.connect(self._open_platform)
        head.addWidget(manage)
        form.addLayout(head)

    def _open_platform(self) -> None:
        """开平台组件面板

        - 关回来按装机结果重灌下拉，原来选的那项还在就保留
        """
        open_platform_dialog(parent=self)
        self._reload_platforms()

    def _reload_platforms(self) -> None:
        """重灌平台下拉并保持原选

        - 原来那项已不在即回到未选状态
        """
        chosen = self._chosen
        self._platform.blockSignals(True)
        fill_combo(self._platform, _platform_items())
        self._platform.setCurrentIndex(self._index_of(chosen))
        self._platform.blockSignals(False)
        self._on_platform_changed(self._platform.currentIndex())

    def _index_of(self, platform: PlatformCode | None) -> int:
        """按平台找下拉项的位置"""
        if platform is None:
            return -1
        for index in range(self._platform.count()):
            if PlatformCode(self._platform.itemData(index)) == platform:
                return index
        return -1

    def _on_platform_changed(self, _index: int) -> None:
        """换平台即换凭证块

        - 选到另一个平台时清空凭证输入，备注保留
        - 声明取不到就收起凭证块，留一句人话
        """
        data = self._platform.currentData()
        if data is None:
            self._chosen = None
            self._hide_credential()
            return

        platform = PlatformCode(data)
        changed = platform != self._chosen
        if changed:
            self._credential.clear()
        self._chosen = platform

        spec = credential_of(platform)
        if spec is None:
            self._hide_credential()
            self._warn(PickerMessage.FORM_CREDENTIAL_MISSING)
            return
        self._apply_credential(spec)
        if changed:
            self._credential.setFocus()

    def _on_ok(self) -> None:
        """按平台声明校验凭证并新建实例"""
        if self._platform.count() == 0:
            self._warn(PickerMessage.NEW_NEED_ADAPTER)
            return
        if self._platform.currentData() is None:
            self._warn(PickerMessage.NEW_NEED_PLATFORM)
            return

        spec = self._spec
        if spec is None:
            self._warn(PickerMessage.FORM_CREDENTIAL_MISSING)
            return

        credential = self._credential.text().strip()
        code = spec.identity(credential)
        if not code:
            self._warn(spec.invalid)
            return

        try:
            create_profile(code, credential, self._remark.text())
        except OSError:
            self._warn(PickerMessage.FORM_SAVE_FAIL)
            return

        self.code = code
        self.accept()


class EditProfileDialog(_ProfileFormDialog):
    """编辑实例窗

    - 平台按身份码固定，凭证回填后可改
    - 身份码变了即拒绝，不改写自描述文件
    """

    def __init__(self, code: str, remark: str, parent: QWidget | None = None) -> None:
        self._code = code
        super().__init__(PickerMessage.EDIT_TITLE, parent)
        self._remark.setText(remark)
        self._credential.setText(read_token(code))

        platform = platform_of_key(ProfileKey(code))
        spec = credential_of(platform) if platform is not None else None
        if spec is None:
            self._hide_credential()
            return
        self._apply_credential(spec)
        self._credential.setFocus()

    def _on_ok(self) -> None:
        """推导身份码与实例一致才改写"""
        if platform_of_key(ProfileKey(self._code)) is None:
            self._warn(PickerMessage.EDIT_PLATFORM_UNKNOWN)
            return

        spec = self._spec
        if spec is None:
            self._warn(PickerMessage.FORM_CREDENTIAL_MISSING)
            return

        credential = self._credential.text().strip()
        new_code = spec.identity(credential)
        if not new_code:
            self._warn(spec.invalid)
            return
        if new_code != self._code:
            self._warn(PickerMessage.EDIT_CODE_FIXED)
            return

        try:
            update_profile(self._code, credential, self._remark.text())
        except OSError:
            self._warn(PickerMessage.FORM_SAVE_FAIL)
            return

        self.code = self._code
        self.accept()
