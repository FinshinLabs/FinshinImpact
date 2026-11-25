"""按来源保存、完成门与检测记录

- 变更确认、本地校验、检测、写盘按固定顺序走
- 只有本类参与差异与校验，检测记录带指纹和实际代理
"""

import os
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from finshin_sdk.domain import (  # noqa: E402
    ConnectionPlan,
    PlanVerdict,
    ProbeChannel,
    ProbeOutcome,
    ProbeResult,
    ProbeRow,
)
from skin.theme import ButtonSize, ButtonStyle, button_object_name  # noqa: E402
from ui._bridge import gui_bridge  # noqa: E402
from ui._dialogs import ConfigMode, Round, SettingsDialog  # noqa: E402
from ui._windows._controllers import _save, _source_probe, _verify  # noqa: E402
from utils import config_manager  # noqa: E402
from utils.config import (  # noqa: E402
    ProbeRecord,
    changed_groups,
    changed_sections,
    validate_types,
)
from utils.config.models import (  # noqa: E402
    FieldErrors,  # noqa: E402
    FieldSchema,
    TabSchema,
)

_GROUP = "plugin.AI"
_CORE = "core"
_TITLE = "AI 设置"
_ITEM = "plugin.AI.model.url"


class _Logger:
    """替身日志"""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def debug(self, msg: str) -> None:
        self.lines.append(msg)

    def info(self, msg: str) -> None:
        self.lines.append(msg)

    def error(self, msg: str) -> None:
        self.lines.append(msg)

    def send_error(self, msg: str, _exc: Exception) -> None:
        self.lines.append(msg)


async def _never() -> ProbeResult:
    """占位通道"""
    return ProbeResult(accepted=True, effective="http://proxy")


def _plan(reuse_key: object = "http://a") -> ConnectionPlan:
    """最小检测计划"""
    return ConnectionPlan(
        rows=(ProbeRow(row_id="api", title="接口"),),
        channels=(ProbeChannel("api", "接口", 5.0, _never),),
        reuse_key=reuse_key,
        finish=lambda _outcome: PlanVerdict(notice="接口连通"),
    )


def _schema() -> list[TabSchema]:
    """AI 与 core 两类"""
    return [
        TabSchema(
            "模型",
            "plugin.AI.model",
            _GROUP,
            _TITLE,
            "model",
            [FieldSchema("url", "地址", "", "", str, required=True)],
            probe=lambda _values: _plan(),
        ),
        TabSchema(
            "Bot",
            "core.bot",
            _CORE,
            "Bot 设置",
            "bot",
            [
                FieldSchema(
                    "debug",
                    "调试",
                    "",
                    False,
                    bool,
                    (("False", "关闭"), ("True", "开启")),
                )
            ],
        ),
    ]


class _Dialog:
    """面板状态替身"""

    def __init__(self, schema: list[TabSchema], disk: dict, values: dict) -> None:
        self._schema = schema
        self._disk = deepcopy(disk)
        self.values = deepcopy(values)
        self.warnings: set[str] = set()
        self.is_setup = True
        self.accepted = False
        self.failures: list[tuple[str, FieldErrors]] = []

    @property
    def dirty_groups(self) -> list[str]:
        return changed_groups(self._schema, self._disk, self.values)

    @property
    def warning_groups(self) -> set[str]:
        return set(self.warnings)

    def get_modified_config(self) -> dict:
        return deepcopy(self.values)

    def disk_values(self) -> dict:
        return deepcopy(self._disk)

    def probe_plan(self, group: str, data=None):
        if group != _GROUP:
            return None
        return _plan((data or self.values)["plugin.AI.model"]["url"])

    def group_title(self, group: str) -> str:
        return _TITLE if group == _GROUP else "Bot 设置"

    def set_busy(self, _busy: bool) -> None:
        pass

    def mark_source_failed(self, group: str, errors: FieldErrors) -> None:
        self.warnings.add(group)
        self.failures.append((group, errors))

    def source_saved(self, group: str, candidate: dict) -> None:
        self._disk.update(
            {key: value for key, value in candidate.items() if key.startswith(group)}
        )
        self.warnings.discard(group)
        if not self.warnings:
            self.is_setup = False

    def restore_disk(self) -> None:
        self.values = deepcopy(self._disk)

    def accept(self) -> None:
        self.accepted = True


class _Probe:
    """显式检测替身"""

    def __init__(self) -> None:
        self.verified: dict[str, ProbeRecord] = {}
        self.started: list[str] = []
        self.done = None

    def start(self, group, _plan, done, _cancelled) -> bool:
        self.started.append(group)
        self.done = done

        def complete(record, errors) -> None:
            if record is None:
                self.verified.pop(group, None)
            else:
                self.verified[group] = record
            done(record, errors)

        self.complete = complete
        return True


def _host(dialog: _Dialog) -> SimpleNamespace:
    """保存协调器宿主"""
    return SimpleNamespace(
        _panel=dialog,
        _probe=_Probe(),
        _verify=SimpleNamespace(
            validating=False,
            pending_aborts=None,
            save_pending=False,
            drop_pending=lambda: None,
            abort_pending=lambda: None,
        ),
        logger=_Logger(),
    )


class SourceSaveTest(unittest.TestCase):
    """单类保存顺序与完成门"""

    def setUp(self) -> None:
        self._old_schema = config_manager._schema
        self._old_config = config_manager._config
        config_manager._schema = _schema()
        self.disk = {
            "plugin.AI.model": {"url": "http://a"},
            "core.bot": {"debug": False},
        }
        config_manager._config = deepcopy(self.disk)
        self.dialog = _Dialog(config_manager._schema, self.disk, deepcopy(self.disk))
        self.host = _host(self.dialog)
        self.save = _save.SaveCoordinator(self.host)
        self.requests: list[object] = []
        sig = gui_bridge.config_source
        sig.connect(self.requests.append, f"source-save-{self.id()}")
        self.addCleanup(sig._instance.disconnect, self.requests.append)

    def tearDown(self) -> None:
        config_manager._schema = self._old_schema
        config_manager._config = self._old_config

    def test_unchanged_without_warning_only_notifies(self) -> None:
        with patch.object(_save.NoticeDialog, "notify") as notify:
            self.save.requested(self.dialog, _GROUP)
        notify.assert_called_once()
        self.assertEqual(self.host._probe.started, [])
        self.assertEqual(self.requests, [])

    def test_cancel_change_does_nothing(self) -> None:
        self.dialog.values["plugin.AI.model"]["url"] = "http://b"
        with patch.object(_save.ChangeConfirmDialog, "confirm", return_value=False):
            self.save.requested(self.dialog, _GROUP)
        self.assertFalse(self.save.busy)
        self.assertEqual(self.host._probe.started, [])
        self.assertEqual(self.requests, [])

    def test_local_failure_never_starts_probe(self) -> None:
        self.dialog.values["plugin.AI.model"]["url"] = ""
        with patch.object(_save.ChangeConfirmDialog, "confirm", return_value=True):
            self.save.requested(self.dialog, _GROUP)
        self.assertEqual(self.dialog.failures[0][0], _GROUP)
        self.assertEqual(self.host._probe.started, [])
        self.assertEqual(self.requests, [])

    def test_probe_then_manager_carries_record(self) -> None:
        self.dialog.values["plugin.AI.model"]["url"] = "http://b"
        with patch.object(_save.ChangeConfirmDialog, "confirm", return_value=True):
            self.save.requested(self.dialog, _GROUP)
        self.assertEqual(self.host._probe.started, [_GROUP])
        record = ProbeRecord("http://b", "http://proxy")
        self.host._probe.complete(record, {})
        request = self.requests[0]
        self.assertTrue(request.write)
        self.assertFalse(hasattr(request, "restart"))
        self.assertEqual(request.probes[_GROUP], record)

    def test_warning_only_skips_confirmation_and_write(self) -> None:
        self.dialog.warnings.add(_GROUP)
        with patch.object(_save.ChangeConfirmDialog, "confirm") as confirm:
            self.save.requested(self.dialog, _GROUP)
        confirm.assert_not_called()
        self.host._probe.complete(ProbeRecord("http://a", ""), {})
        self.assertFalse(self.requests[0].write)
        self.assertFalse(hasattr(self.requests[0], "restart"))

    def test_core_save_does_not_restart_edit_service(self) -> None:
        self.dialog.is_setup = False
        self.dialog.values["core.bot"]["debug"] = True
        with patch.object(_save.ChangeConfirmDialog, "confirm", return_value=True):
            self.save.requested(self.dialog, _CORE)
        self.assertTrue(self.requests[0].write)
        self.assertFalse(hasattr(self.requests[0], "restart"))
        self.assertEqual(self.host._probe.started, [])

    def test_manager_recheck_cancel_unlocks_panel(self) -> None:
        self.host.gui = None
        self.host._save = self.save
        self.host._verify = _verify.VerifyCoordinator(self.host)
        self.save._busy = True
        self.save._pending_group = _GROUP
        self.host._verify.save_pending = True
        with patch.object(gui_bridge.config_abort, "emit"):
            self.host._verify.abort_pending()
        self.assertFalse(self.save.busy)
        self.assertFalse(self.host._verify.save_pending)

    def test_finish_discards_all_drafts(self) -> None:
        self.dialog.is_setup = False
        self.dialog.values["plugin.AI.model"]["url"] = "http://b"
        with patch.object(_save.ChangeConfirmDialog, "confirm", return_value=True):
            self.save.finish(self.dialog)
        self.assertEqual(self.dialog.values, self.disk)
        self.assertTrue(self.dialog.accepted)

    def test_finish_emits_verified_once_after_write(self) -> None:
        self.dialog.warnings.add(_GROUP)
        self.save._busy = True
        self.save._pending_group = _GROUP
        self.save._candidate = deepcopy(self.dialog.values)
        self.save.wrote = True
        record = ProbeRecord("http://a", "http://proxy")
        received: list[dict[str, ProbeRecord]] = []
        signal = gui_bridge.config_sources_verified
        signal.connect(received.append, f"source-verified-{self.id()}")
        self.addCleanup(signal._instance.disconnect, received.append)

        self.save.source_done(self.dialog, _GROUP, True, {}, record)

        self.assertFalse(self.dialog.is_setup)
        self.assertEqual(received, [], "转编辑态不得发送启动回执")
        self.save.finish(self.dialog)
        self.assertEqual(received, [{_GROUP: record}])
        self.assertFalse(self.save._pending_apply)
        self.assertTrue(self.dialog.accepted)

    def test_finish_without_write_does_not_emit_verified(self) -> None:
        self.dialog.is_setup = False
        received: list[dict[str, ProbeRecord]] = []
        signal = gui_bridge.config_sources_verified
        signal.connect(received.append, f"source-verified-{self.id()}")
        self.addCleanup(signal._instance.disconnect, received.append)

        self.save.finish(self.dialog)

        self.assertEqual(received, [])
        self.assertTrue(self.dialog.accepted)

    def test_reset_pending_clears_previous_window_write(self) -> None:
        self.dialog.is_setup = False
        self.save._pending_apply = True
        self.save.reset_pending()
        received: list[dict[str, ProbeRecord]] = []
        signal = gui_bridge.config_sources_verified
        signal.connect(received.append, f"source-verified-{self.id()}")
        self.addCleanup(signal._instance.disconnect, received.append)

        self.save.finish(self.dialog)

        self.assertEqual(received, [])
        self.assertTrue(self.dialog.accepted)


class SourceDiffTest(unittest.TestCase):
    """缺键按 schema 默认值比较"""

    def test_missing_key_matching_default_is_not_dirty(self) -> None:
        schema = [
            TabSchema(
                "模型",
                "plugin.AI.model",
                _GROUP,
                _TITLE,
                "model",
                [FieldSchema("mode", "模式", "", "auto", str)],
            )
        ]
        values = {"plugin.AI.model": {"mode": "auto"}}
        self.assertEqual(changed_groups(schema, {}, values), [])
        values["plugin.AI.model"]["mode"] = "manual"
        self.assertEqual(changed_groups(schema, {}, values), [_GROUP])

    def test_changed_sections_only_marks_changed_tabs(self) -> None:
        schema = [
            *_schema(),
            TabSchema(
                "高级",
                "plugin.AI.advanced",
                _GROUP,
                _TITLE,
                "advanced",
                [FieldSchema("mode", "模式", "", "auto", str)],
            ),
        ]
        disk = {
            "plugin.AI.model": {"url": "http://a"},
            "plugin.AI.advanced": {"mode": "auto"},
            "core.bot": {"debug": False},
        }
        one = deepcopy(disk)
        one["plugin.AI.model"]["url"] = "http://b"
        two = deepcopy(one)
        two["plugin.AI.advanced"]["mode"] = "manual"
        cases = [
            ("one", one, ["plugin.AI.model"]),
            ("two", two, ["plugin.AI.model", "plugin.AI.advanced"]),
            ("none", deepcopy(disk), []),
        ]
        for name, values, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(changed_sections(schema, disk, values), expected)
        self.assertEqual(changed_sections(schema, {}, {}), [])


class SettingsDialogMarksTest(unittest.TestCase):
    """进场错误、并存标记与 Esc、关窗判定"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.schema = _schema()
        self.disk = {
            "plugin.AI.model": {"url": ""},
            "core.bot": {"debug": False},
        }
        errors = validate_types(self.schema, self.disk)
        self.dialog = SettingsDialog(
            self.schema,
            self.disk,
            mode=ConfigMode.SETUP,
            field_errors=errors,
        )
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_initial_error_marks_whole_group(self) -> None:
        self.assertIn(_GROUP, self.dialog.warning_groups)
        tab = self.dialog._chrome._group_tabs[_GROUP]
        self.assertTrue(tab.tabText(0).startswith("⚠"))

    def test_setup_bottom_only_has_exit_and_source_save_is_primary(self) -> None:
        self.assertIsNone(self.dialog._chrome.save_btn)
        self.assertEqual(self.dialog._chrome.bottom_layout.count(), 2)
        bar = self.dialog._chrome.bottom_layout.itemAt(1).widget()
        self.assertEqual(
            [button.text() for button in bar.findChildren(QPushButton)], ["退出程序"]
        )
        source_button = self.dialog._chrome._group_tabs[_GROUP].cornerWidget(
            Qt.Corner.TopRightCorner
        )
        self.assertEqual(
            source_button.objectName(),
            button_object_name(ButtonStyle.PRIMARY, ButtonSize.SMALL),
        )

    def test_setup_busy_locks_navigation_and_source_save(self) -> None:
        self.dialog.set_busy(True)
        self.assertFalse(self.dialog._chrome._categories.isEnabled())
        for tabs in self.dialog._chrome._group_tabs.values():
            self.assertFalse(tabs.isEnabled())
            self.assertFalse(tabs.cornerWidget(Qt.Corner.TopRightCorner).isEnabled())

        self.dialog.set_busy(False)
        self.assertTrue(self.dialog._chrome._categories.isEnabled())
        for tabs in self.dialog._chrome._group_tabs.values():
            self.assertTrue(tabs.isEnabled())
            self.assertTrue(tabs.cornerWidget(Qt.Corner.TopRightCorner).isEnabled())

    def test_dirty_and_warning_use_separate_marks(self) -> None:
        self.dialog._fields.inputs[
            next(tab.path_of(field) for tab in self.schema for field in tab.fields)
        ].setText("http://b")
        self.app.processEvents()
        self.assertIn(_GROUP, self.dialog.dirty_groups)
        self.assertIn(_GROUP, self.dialog.warning_groups)
        item = self.dialog._chrome._category_items[_GROUP][0]
        tab = self.dialog._chrome._group_tabs[_GROUP]
        self.assertEqual(item.text(), "⚠ AI 设置 ✏️")
        self.assertEqual(tab.tabText(0), "⚠ 模型 ✏️")

    def test_source_saved_clears_errors_and_returns_to_edit(self) -> None:
        tab_schema = self.schema[0]
        item = tab_schema.path_of(tab_schema.fields[0])
        label = self.dialog._fields.labels[item][0]
        self.assertNotEqual(label.styleSheet(), "")
        self.dialog._fields.inputs[item].setText("http://b")
        self.app.processEvents()

        self.dialog.source_saved(_GROUP, self.dialog.get_modified_config())

        self.assertFalse(self.dialog.is_setup)
        self.assertNotIn(_GROUP, self.dialog.warning_groups)
        self.assertNotIn(item, self.dialog._field_errors)
        self.assertEqual(label.styleSheet(), "")
        self.assertEqual(label.toolTip(), "")
        self.assertEqual(self.dialog._chrome._group_tabs[_GROUP].tabText(0), "模型")
        self.assertEqual(
            self.dialog._chrome._category_items[_GROUP][0].text(), "AI 设置"
        )
        self.assertEqual(self.dialog._chrome.bottom_layout.count(), 1)
        bar = self.dialog._chrome.bottom_layout.itemAt(0).widget()
        self.assertEqual(
            [button.text() for button in bar.findChildren(QPushButton)], ["完成"]
        )

    def test_switched_setup_discards_back_to_disk(self) -> None:
        """编辑态转向导后可放弃改动回盘上值"""
        dialog = SettingsDialog(self.schema, self.disk, mode=ConfigMode.EDIT)
        dialog.show()
        self.app.processEvents()
        item = self.schema[0].path_of(self.schema[0].fields[0])
        dialog._fields.inputs[item].setText("http://bad")
        self.app.processEvents()

        dialog.switch_to_setup({})
        bar = dialog._chrome.bottom_layout.itemAt(1).widget()
        buttons = bar.findChildren(QPushButton)
        self.assertEqual(
            [button.text() for button in buttons], ["放弃改动", "退出程序"]
        )

        next(button for button in buttons if button.text() == "放弃改动").click()
        self.assertFalse(dialog.is_setup)
        self.assertEqual(dialog._fields.inputs[item].text(), "")
        self.assertEqual(dialog.dirty_groups, [])
        dialog.deleteLater()
        self.app.processEvents()

    def test_source_saved_keeps_setup_until_last_warning_clears(self) -> None:
        core_schema = self.schema[1]
        core_item = core_schema.path_of(core_schema.fields[0])
        self.dialog.apply_errors(
            {**self.dialog._field_errors, core_item: "Bot 设置未通过"}
        )
        self.assertEqual(self.dialog.warning_groups, {_GROUP, _CORE})

        self.dialog._fields.inputs[
            self.schema[0].path_of(self.schema[0].fields[0])
        ].setText("http://b")
        self.app.processEvents()
        self.dialog.source_saved(_GROUP, self.dialog.get_modified_config())

        self.assertTrue(self.dialog.is_setup)
        self.assertEqual(self.dialog.warning_groups, {_CORE})
        self.assertEqual(self.dialog._chrome._group_tabs[_GROUP].tabText(0), "模型")
        self.assertEqual(self.dialog._chrome._group_tabs[_CORE].tabText(0), "⚠ Bot")
        self.assertEqual(
            self.dialog._chrome._category_items[_CORE][0].text(), "⚠ Bot 设置"
        )
        self.assertNotEqual(self.dialog._fields.labels[core_item][0].styleSheet(), "")

        self.dialog.source_saved(_CORE, self.dialog.get_modified_config())

        self.assertFalse(self.dialog.is_setup)
        self.assertEqual(self.dialog.warning_groups, set())
        self.assertEqual(self.dialog._field_errors, {})
        self.assertEqual(self.dialog._chrome._group_tabs[_CORE].tabText(0), "Bot")
        self.assertEqual(
            self.dialog._chrome._category_items[_CORE][0].text(), "Bot 设置"
        )

    def test_mark_layouts_keep_warning_left_and_dirty_right(self) -> None:
        section = self.schema[0].section
        cases = [
            (
                "both",
                {section},
                [_GROUP],
                [section],
                {_GROUP},
                "⚠ AI 设置 ✏️",
                "⚠ 模型 ✏️",
            ),
            (
                "dirty",
                set(),
                [_GROUP],
                [section],
                set(),
                "AI 设置 ✏️",
                "模型 ✏️",
            ),
            (
                "group",
                set(),
                [_GROUP],
                [],
                set(),
                "AI 设置 ✏️",
                "模型",
            ),
            (
                "warning",
                {section},
                [],
                [],
                {_GROUP},
                "⚠ AI 设置",
                "⚠ 模型",
            ),
            ("clean", set(), [], [], set(), "AI 设置", "模型"),
        ]
        for name, errors, dirty, dirty_sections, warnings, category, tab in cases:
            with self.subTest(name=name):
                self.dialog._chrome.set_error_marks(
                    errors, dirty, dirty_sections, warnings
                )
                item = self.dialog._chrome._category_items[_GROUP][0]
                tabs = self.dialog._chrome._group_tabs[_GROUP]
                self.assertEqual(item.text(), category)
                self.assertEqual(tabs.tabText(0), tab)

    def test_escape_and_close_only_finish_in_edit(self) -> None:
        finished: list[bool] = []
        self.dialog.finish_requested.connect(lambda: finished.append(True))
        QTest.keyClick(self.dialog, Qt.Key.Key_Escape)
        self.dialog.close()
        self.assertEqual(finished, [])
        self.assertTrue(self.dialog.isVisible())

        self.dialog.switch_to_edit()
        QTest.keyClick(self.dialog, Qt.Key.Key_Escape)
        self.dialog.close()
        self.assertEqual(finished, [True, True])
        self.assertTrue(self.dialog.isVisible())


class SettingsSourceValidationTest(unittest.IsolatedAsyncioTestCase):
    """保存与启动复用的来源边界"""

    async def test_non_adapter_group_ignores_other_required_group(self) -> None:
        from bot._managers import _settings as mod

        schema = deepcopy(_schema())
        core = schema[1]
        core.fields = [FieldSchema("name", "名称", "", "", str, required=True)]
        values = {
            "plugin.AI.model": {"url": "http://a"},
            "core.bot": {"name": ""},
        }
        manager = mod.SettingsManager(lambda: "token")
        with (
            patch.object(mod, "get_schema", return_value=schema),
            patch.object(mod.config_manager, "get_all", return_value=values),
        ):
            passed = await manager.verify_connectivity(group=_GROUP)
        self.assertTrue(passed)
        self.assertEqual(manager.last_errors, {})

    async def test_non_adapter_group_does_not_run_network(self) -> None:
        from bot._managers import _settings as mod

        manager = mod.SettingsManager(lambda: "token")
        with (
            patch.object(mod, "get_schema", return_value=_schema()),
            patch.object(
                mod.config_manager,
                "get_all",
                return_value={
                    "plugin.AI.model": {"url": "http://a"},
                    "core.bot": {"debug": False},
                },
            ),
            patch.object(mod, "run_probe_round") as run,
        ):
            passed = await manager.verify_connectivity(group=_GROUP)
        self.assertTrue(passed)
        run.assert_not_called()


class ProbeRecordTest(unittest.TestCase):
    """检测协调器的通过记录"""

    def _coordinator(self, verified=None):
        panel = SimpleNamespace(
            set_busy=lambda _busy: None, apply_source_errors=lambda *a: None
        )
        host = SimpleNamespace(
            _panel=panel, logger=_Logger(), _verify=SimpleNamespace()
        )
        coord = _source_probe.SourceProbeCoordinator(host)
        coord.verified.update(verified or {})
        coord._token = 3
        coord._group = _GROUP
        coord._plan = _plan()
        coord._done = lambda *_args: None
        return coord

    def test_pass_records_proxy(self) -> None:
        coord = self._coordinator()
        outcome = ProbeOutcome(accepted=ProbeResult(True, effective="http://proxy"))
        with patch.object(_source_probe, "current_check_window", return_value=None):
            coord._on_done(3, outcome)
        self.assertEqual(
            coord.verified, {_GROUP: ProbeRecord("http://a", "http://proxy")}
        )

    def test_fail_clears_record(self) -> None:
        coord = self._coordinator({_GROUP: ProbeRecord("old", "")})
        with patch.object(_source_probe, "current_check_window", return_value=None):
            coord._on_done(3, ProbeOutcome())
        self.assertEqual(coord.verified, {})

    def test_pass_closes_check_window_without_result_frame(self) -> None:
        coord = self._coordinator()
        win = SimpleNamespace(
            round=Round.PROBE,
            is_running=True,
            settle_and_close=Mock(),
            apply=Mock(),
        )
        outcome = ProbeOutcome(accepted=ProbeResult(True, effective="http://proxy"))
        with patch.object(_source_probe, "current_check_window", return_value=win):
            coord._on_done(3, outcome)
        win.settle_and_close.assert_called_once_with(True)
        win.apply.assert_not_called()

    def test_fail_keeps_result_window_open(self) -> None:
        coord = self._coordinator()
        win = SimpleNamespace(
            round=Round.PROBE,
            is_running=True,
            settle_and_close=Mock(),
            apply=Mock(),
        )
        with patch.object(_source_probe, "current_check_window", return_value=win):
            coord._on_done(3, ProbeOutcome())
        win.settle_and_close.assert_not_called()
        win.apply.assert_called_once()

    def test_stale_token_ignored(self) -> None:
        coord = self._coordinator()
        with patch.object(_source_probe, "current_check_window", return_value=None):
            coord._on_done(2, ProbeOutcome(accepted=ProbeResult(True)))
        self.assertEqual(coord.verified, {})
        self.assertIsNotNone(coord._plan)


if __name__ == "__main__":
    unittest.main()
