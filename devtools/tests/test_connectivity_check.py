"""连接性检查的单元测试

- 校验轮只按适配器交的检查计划跑通道，缺席与去重行由计划直接给结论
- 网络轮只在计划输入变化、上轮连通未过或引擎断线时起，其余只跑本地
- 系统代理地址只计进用得到它的那几档
- 首轮全挂预热后重检一轮，单路档同样重检本路
"""

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from adapter_presence import adapter_present  # noqa: E402
from config_plan import assemble_for_case, fake_adapter_parts  # noqa: E402

from finshin_sdk.domain import ProbeResult  # noqa: E402
from finshin_sdk.domain.config import ConfigPath  # noqa: E402
from finshin_sdk.exceptions import ProbeTimeoutError  # noqa: E402
from skin.messages import CheckMessage  # noqa: E402
from utils.check import _verify as verify_mod  # noqa: E402
from utils.config import ProbeRecord  # noqa: E402
from utils.network import CHECKING  # noqa: E402

_ADAPTER_LOADED = adapter_present()


def _errors():
    """取已装适配器的异常族"""
    from finshin_adapter_tg import _errors as mod

    return mod


def _plan_mod():
    """取已装适配器的检查计划件"""
    from finshin_adapter_tg import _plan

    return _plan


def _probe_mod():
    """取已装适配器的探测件，未装载即跳过"""
    from finshin_adapter_tg import _probe

    return _probe


def _proxy_item():
    """代理项身份由适配器交出"""
    return _probe_mod().PROXY_ITEM


def _token_item():
    """凭证项身份由适配器交出"""
    from finshin_adapter_tg._credential import CREDENTIAL

    return CREDENTIAL.item


def _mode_item():
    """代理模式项身份由适配器交出"""
    return _plan_mod()._MODE_ITEM


_TYPE_ITEM = ConfigPath(source="plugin.ai", section="model", key="temperature")
_CFG_DEAD = "http://127.0.0.1:9999"
_CFG_ALIVE = "http://127.0.0.1:7890"


@contextmanager
def _patched(
    mod,
    fake_check,
    *,
    mode="auto",
    cfg="",
    types=None,
    link_down=False,
    sys_box=None,
    sys_proxy=None,
):
    """统一打桩

    - 通道探测、结果文案、本地校验、系统代理、链路快照与重检预热
    - fake_check 按 (token, proxy) 返回错误字典，键为代理项或 token
    - sys_box 传入即 {"value": 地址} 盒子，现取现换用于测系统代理变化
    """
    local = ({"id": "local", "status": "ok", "detail": ""}, types or {})
    probe = _probe_mod()
    plan = _plan_mod()

    async def fake_run(token: str, proxy: str, budget: float) -> ProbeResult:
        errors = await fake_check(token, proxy)
        texts = {key: probe._describe(value) for key, value in errors.items()}
        accepted = probe.PROXY_ITEM not in errors
        return ProbeResult(
            accepted=accepted,
            field_errors=texts,
            effective=proxy if accepted and not texts else None,
        )

    def detected() -> str | None:
        return sys_box["value"] if sys_box is not None else sys_proxy

    report = SimpleNamespace(snapshot=lambda: SimpleNamespace(down=link_down))
    values = {"adapter.tg.proxy": {"proxy_mode": mode, "proxy": cfg}}
    with (
        patch.object(plan, "run_channel", fake_run),
        patch.object(mod, "local_row", return_value=local),
        patch.object(mod, "detect_system_proxy", detected),
        patch.object(mod, "link_report", report),
        patch.object(mod.config_manager, "get_all", return_value=values),
        patch.object(verify_mod, "_RETRY_WARMUP", 0.0),
    ):
        yield


@unittest.skipUnless(_ADAPTER_LOADED, "适配层未装载，连接校验用例跳过")
class TestVerifyConnectivityAggregation(unittest.IsolatedAsyncioTestCase):
    """回归点

    - 自动档按配置→系统→直连解析与错误聚合
    - 免测判据由连通结论、引擎断线与计划输入共同把关
    """

    async def test_source_save_reruns_same_record(self) -> None:
        """单类保存不拿启动指纹跳过本类检测"""
        from bot._managers._settings import SettingsManager

        calls = 0

        async def good(_token: str, _proxy: str) -> dict:
            nonlocal calls
            calls += 1
            return {}

        manager = SettingsManager(lambda: "tok")
        record = ProbeRecord(("auto", "", ""), "http://proxy")
        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, good):
            passed = await manager.verify_connectivity(
                group="adapter.tg", probes={"adapter.tg": record}
            )
        self.assertTrue(passed)
        self.assertEqual(calls, 1)
        self.assertEqual(manager.resolved_proxy, "")
        self.assertIsNotNone(manager.last_probe)

    async def test_startup_reuses_record_without_network(self) -> None:
        """向导完成交来的同指纹记录只恢复通道，不发探测"""
        from bot._managers._settings import SettingsManager

        calls = 0

        async def dead(_token: str, _proxy: str) -> dict:
            nonlocal calls
            calls += 1
            return {
                _proxy_item(): _errors().ProxyConnectionRefusedError(proxy=_CFG_DEAD)
            }

        manager = SettingsManager(lambda: "tok")
        record = ProbeRecord(("auto", "", ""), "http://proxy")
        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, dead):
            passed = await manager.verify_connectivity(probes={"adapter.tg": record})
        self.assertTrue(passed)
        self.assertEqual(calls, 0)
        self.assertEqual(manager.resolved_proxy, "http://proxy")

    async def test_startup_checks_all_local_fields(self) -> None:
        """普通启动的本地校验覆盖全部来源"""
        from bot._managers._settings import SettingsManager

        async def good(_token: str, _proxy: str) -> dict:
            return {}

        manager = SettingsManager(lambda: "tok")
        mod = sys.modules["bot._managers._settings"]
        errors = {_TYPE_ITEM: "类型错误"}
        with _patched(mod, good, types=errors):
            passed = await manager.verify_connectivity()
            group = mod.local_row.call_args.kwargs["group"]
        self.assertFalse(passed)
        self.assertEqual(manager.last_errors, errors)
        self.assertIsNone(group)

    async def test_all_channels_fail_aggregates(self) -> None:
        """自动档三路全不通

        - 聚合为一句跨路汇总
        - 尾句指向代理软件自查
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")

        async def dead(token: str, proxy: str) -> dict:
            return {
                _proxy_item(): _errors().ProxyConnectionRefusedError(proxy=_CFG_DEAD)
            }

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, dead, cfg=_CFG_DEAD):
            ok = await mgr.verify_connectivity()

        self.assertFalse(ok)
        self.assertIsNone(mgr.resolved_proxy)
        self.assertEqual(list(mgr.last_errors), [_proxy_item()])
        self.assertIn("均无法连通", mgr.last_errors[_proxy_item()])
        self.assertIn("代理软件", mgr.last_errors[_proxy_item()])

    async def test_fallback_direct_when_config_dead(self) -> None:
        """配置代理死、直连通

        - 生效通道=直连，net 残留清零
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")

        async def only_direct(token: str, proxy: str) -> dict:
            return (
                {}
                if not proxy
                else {
                    _proxy_item(): _errors().ProxyConnectionRefusedError(
                        proxy=_CFG_DEAD
                    )
                }
            )

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, only_direct, cfg=_CFG_DEAD):
            ok = await mgr.verify_connectivity()

        self.assertTrue(ok)
        self.assertEqual(mgr.resolved_proxy, "")
        self.assertEqual(mgr.last_errors, {})

    async def test_token_error_stops_channel_switch(self) -> None:
        """通道已通仅 token 无效

        - 不换道不聚合，原样上报
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")

        async def token_bad(token: str, proxy: str) -> dict:
            return {_token_item(): _errors().TokenError()}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, token_bad, cfg="prox"):
            ok = await mgr.verify_connectivity()

        self.assertFalse(ok)
        self.assertIsNone(mgr.resolved_proxy)
        self.assertEqual(mgr.last_errors, {_token_item(): "Token 无效"})

    async def test_single_candidate_keeps_original_error(self) -> None:
        """仅直连单候选不通

        - 代理留空且无系统代理
        - 保留原始网络错误文案，不跨路聚合
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")

        async def dead_direct(token: str, proxy: str) -> dict:
            return {_proxy_item(): _errors().DirectTimeoutError()}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, dead_direct):
            ok = await mgr.verify_connectivity()

        self.assertFalse(ok)
        self.assertIsNone(mgr.resolved_proxy)
        self.assertIn("直连超时", mgr.last_errors[_proxy_item()])
        self.assertNotIn("均无法连通", mgr.last_errors[_proxy_item()])
        self.assertIn("代理软件", mgr.last_errors[_proxy_item()])

    async def test_network_and_type_errors_merged(self) -> None:
        """连通性与类型错误合并上报

        - 网络项在前、类型项在后
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")

        async def net_fail(token: str, proxy: str) -> dict:
            return {_proxy_item(): _errors().ProxySchemeError(scheme="https")}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, net_fail, cfg="prox", types={_TYPE_ITEM: "类型应为 float"}):
            ok = await mgr.verify_connectivity()

        self.assertFalse(ok)
        self.assertEqual(
            list(mgr.last_errors),
            [_proxy_item(), _TYPE_ITEM],
            "错误顺序应为网络在前、类型在后",
        )

    async def test_unchanged_params_run_local_only(self) -> None:
        """计划输入未变的二次校验只跑本地

        - 免测轮不联网，也不发整表帧
        """
        from unittest.mock import MagicMock

        from bot._managers._settings import SettingsManager
        from utils.network import FrameKey

        mgr = SettingsManager(lambda: "tok")
        probes: list[str] = []

        async def alive(token: str, proxy: str) -> dict:
            probes.append(proxy)
            return {}

        frames: list[dict] = []
        bridge = MagicMock()
        bridge.verify_progress.emit.side_effect = frames.append

        mod = sys.modules["bot._managers._settings"]
        with (
            _patched(mod, alive, cfg=_CFG_ALIVE),
            patch.object(mod, "gui_bridge", bridge),
        ):
            self.assertTrue(await mgr.verify_connectivity())
            self.assertTrue(probes, "首轮应联网探测")
            probes.clear()
            frames.clear()
            self.assertTrue(await mgr.verify_connectivity())

        self.assertEqual(probes, [], "计划输入没变不该再联网")
        self.assertEqual(
            [f for f in frames if FrameKey.ROWS in f],
            [],
            "免测轮不发整表帧",
        )
        self.assertEqual(len(frames), 1, "免测轮只发结论帧")

    async def test_token_change_not_a_network_round(self) -> None:
        """只换 token 不单点复查通道

        - token 不进计划输入，未变即免测
        """
        from bot._managers._settings import SettingsManager

        getter = {"token": "tok1"}
        mgr = SettingsManager(lambda: getter["token"])
        probes: list[str] = []

        async def alive(token: str, proxy: str) -> dict:
            probes.append(token)
            return {}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, alive, cfg=_CFG_ALIVE):
            self.assertTrue(await mgr.verify_connectivity())
            getter["token"] = "tok2"
            probes.clear()
            self.assertTrue(await mgr.verify_connectivity())

        self.assertEqual(probes, [], "token 变动不该起联网轮")

    async def test_type_error_alone_keeps_local_only(self) -> None:
        """上轮只报本地类型错时保持免测

        - 计划输入没变且连通已过，类型错走免测轮复查
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        probes: list[str] = []

        async def alive(token: str, proxy: str) -> dict:
            probes.append(proxy)
            return {}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, alive, types={_TYPE_ITEM: "类型应为 float"}):
            self.assertFalse(await mgr.verify_connectivity())
            self.assertTrue(probes, "首轮应联网探测")
            self.assertIsNotNone(mgr.resolved_proxy, "直连通了应记下生效通道")
            self.assertTrue(mgr.link_verified, "通道探通即连通已过，本地类型错不牵连")
            probes.clear()
            self.assertFalse(await mgr.verify_connectivity())

        self.assertEqual(probes, [], "只有类型错时不该重联网")

    async def test_proxy_error_forces_network_retest(self) -> None:
        """上轮代理不通作废免测

        - 连通判据没立起，计划输入没变也要重探
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        probes: list[str] = []
        reach = {"ok": False}

        async def dead_then_alive(token: str, proxy: str) -> dict:
            probes.append(proxy)
            return (
                {}
                if reach["ok"]
                else {
                    _proxy_item(): _errors().ProxyConnectionRefusedError(
                        proxy=_CFG_DEAD
                    )
                }
            )

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, dead_then_alive, cfg=_CFG_DEAD):
            self.assertFalse(await mgr.verify_connectivity())
            self.assertIsNone(mgr.resolved_proxy, "全挂时不该记下生效通道")
            self.assertFalse(mgr.link_verified, "全挂即连通未过")
            probes.clear()
            reach["ok"] = True
            self.assertTrue(await mgr.verify_connectivity())
            self.assertTrue(mgr.link_verified, "重探通后连通判据立起")

        self.assertTrue(probes, "上轮不通不该免测")

    async def test_link_down_vetoes_local_only(self) -> None:
        """引擎正断线时作废免测

        - 计划输入一字未改、上轮连通也过了，仍要重探一轮
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        probes: list[str] = []

        async def alive(token: str, proxy: str) -> dict:
            probes.append(proxy)
            return {}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, alive, cfg=_CFG_ALIVE):
            self.assertTrue(await mgr.verify_connectivity())
            probes.clear()

        with _patched(mod, alive, cfg=_CFG_ALIVE, link_down=True):
            self.assertTrue(await mgr.verify_connectivity())

        self.assertTrue(probes, "断连周期在途时不该只跑本地")

    async def test_sys_proxy_change_forces_network_retest(self) -> None:
        """系统代理地址一变作废免测

        - 自动档用得到注册表那一项，开关一拨旧结论就不作数
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        sys_box = {"value": _CFG_ALIVE}
        probes: list[str] = []

        async def alive(token: str, proxy: str) -> dict:
            probes.append(proxy)
            return {}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, alive, sys_box=sys_box):
            self.assertTrue(await mgr.verify_connectivity())
            self.assertTrue(mgr.link_verified, "首轮探通即连通已过")
            probes.clear()
            sys_box["value"] = None
            self.assertTrue(await mgr.verify_connectivity())

        self.assertTrue(probes, "系统代理消失属计划输入变了")


@unittest.skipUnless(_ADAPTER_LOADED, "适配层未装载，代理档位用例跳过")
class TestProxyModeFlow(unittest.IsolatedAsyncioTestCase):
    """回归点

    - 单路档只探选定通道，失败不跨路聚合
    - 每种档位首轮全挂都等待预热后重检一轮
    - 重检轮开场重发整表，待测行刷回检测中并带头部重测提示
    - 代理行被隐藏的档位，网络错标在看得见的代理模式行上
    - 用不到系统代理的档位，其地址变化不作废免测
    """

    def setUp(self) -> None:
        """装配一次段表，配置读写走装配后的段名"""
        assemble_for_case(self)

    async def test_single_cfg_probes_only_config(self) -> None:
        """仅配置代理档不探直连"""
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        seen: list[str] = []

        async def probe(token: str, proxy: str) -> dict:
            seen.append(proxy)
            return {}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, probe, mode="cfg", cfg=_CFG_DEAD):
            ok = await mgr.verify_connectivity()

        self.assertTrue(ok)
        self.assertEqual(seen, [_CFG_DEAD], "单路配置档不得探测直连")
        self.assertEqual(mgr.resolved_proxy, _CFG_DEAD)

    async def test_single_cfg_fail_reports_own_error(self) -> None:
        """单路失败只回本路错，不跨路聚合"""
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        calls = {"n": 0}

        async def dead(token: str, proxy: str) -> dict:
            calls["n"] += 1
            return {
                _proxy_item(): _errors().ProxyConnectionRefusedError(proxy=_CFG_DEAD)
            }

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, dead, mode="cfg", cfg=_CFG_DEAD):
            ok = await mgr.verify_connectivity()

        self.assertFalse(ok)
        self.assertEqual(calls["n"], 2, "单路配置档也重检一轮")
        self.assertIn("无法连接到代理服务器", mgr.last_errors[_proxy_item()])
        self.assertNotIn("均无法连通", mgr.last_errors[_proxy_item()])

    async def test_hidden_proxy_mode_takes_the_mark(self) -> None:
        """代理行隐藏的档位，网络错的标红落在代理模式行

        - 仅系统代理与仅直连两档用不到代理项，面板把那一行整行藏掉
        """
        from bot._managers._settings import SettingsManager

        for mode, sys_proxy in (("direct", None), ("sys", _CFG_ALIVE)):
            with self.subTest(mode=mode):
                mgr = SettingsManager(lambda: "tok")

                async def dead(token: str, proxy: str) -> dict:
                    return {
                        _proxy_item(): _errors().ProxyConnectionRefusedError(
                            proxy=_CFG_DEAD
                        )
                    }

                mod = sys.modules["bot._managers._settings"]
                with _patched(mod, dead, mode=mode, cfg=_CFG_DEAD, sys_proxy=sys_proxy):
                    ok = await mgr.verify_connectivity()

                self.assertFalse(ok)
                self.assertEqual(
                    list(mgr.last_errors), [_mode_item()], "红点要落在看得见的行上"
                )
                self.assertIn("无法连接到代理服务器", mgr.last_errors[_mode_item()])

    async def test_single_direct_fail_retries(self) -> None:
        """仅直连档首轮失败同样重检

        - TUN 内核冷启动可能只卡住首探
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        calls = {"n": 0}

        async def cold_start(token: str, proxy: str) -> dict:
            calls["n"] += 1
            if calls["n"] == 1:
                return {_proxy_item(): _errors().DirectTimeoutError()}
            return {}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, cold_start, mode="direct", cfg=_CFG_DEAD):
            ok = await mgr.verify_connectivity()

        self.assertTrue(ok, "重检轮通过即算数")
        self.assertEqual(calls["n"], 2, "直连档应重检一轮")
        self.assertEqual(mgr.resolved_proxy, "")

    async def test_direct_mode_probes_empty_proxy(self) -> None:
        """仅直连档以空 proxy 探测且不误报降级"""
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        seen: list[str] = []

        async def probe(token: str, proxy: str) -> dict:
            seen.append(proxy)
            return {}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, probe, mode="direct", cfg=_CFG_DEAD):
            ok = await mgr.verify_connectivity()

        self.assertTrue(ok)
        self.assertEqual(seen, [""], "直连档应只探空 proxy 一路")
        self.assertEqual(mgr.resolved_proxy, "")

    async def test_sys_mode_absent_no_probe(self) -> None:
        """选系统代理但注册表无地址，缺席不发探测"""
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        calls = {"n": 0}

        async def probe(token: str, proxy: str) -> dict:
            calls["n"] += 1
            return {}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, probe, mode="sys", cfg=""):
            ok = await mgr.verify_connectivity()

        self.assertFalse(ok)
        self.assertEqual(calls["n"], 0, "缺席单路不应发探测")
        self.assertIn("系统代理未开启", mgr.last_errors[_mode_item()])

    async def test_cfg_absent_marks_visible_proxy_row(self) -> None:
        """仅配置代理档没填地址，红点落在代理项

        - 这一档代理行不隐藏，缺席句该标在用户能改的那一格
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        calls = {"n": 0}

        async def probe(token: str, proxy: str) -> dict:
            calls["n"] += 1
            return {}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, probe, mode="cfg", cfg=""):
            ok = await mgr.verify_connectivity()

        self.assertFalse(ok)
        self.assertEqual(calls["n"], 0, "缺席单路不应发探测")
        self.assertEqual(list(mgr.last_errors), [_proxy_item()])

    async def test_direct_mode_ignores_system_proxy_change(self) -> None:
        """仅直连档不吃系统代理变化的免测作废

        - 这一档探不到系统通道，注册表开关一拨与本路无关
        """
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        sys_box = {"value": _CFG_ALIVE}
        seen: list[str] = []

        async def probe(token: str, proxy: str) -> dict:
            seen.append(proxy)
            return {}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, probe, mode="direct", cfg="", sys_box=sys_box):
            self.assertTrue(await mgr.verify_connectivity())
            seen.clear()
            sys_box["value"] = None
            self.assertTrue(await mgr.verify_connectivity())

        self.assertEqual(seen, [], "系统代理变化与仅直连档无关")

    async def test_auto_fail_then_retry_passes(self) -> None:
        """自动档首轮全挂，重检轮通过即算数"""
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        cfg_calls = {"n": 0}

        async def flaky(token: str, proxy: str) -> dict:
            if not proxy:
                return {_proxy_item(): _errors().DirectTimeoutError()}
            cfg_calls["n"] += 1
            return {_proxy_item(): ProbeTimeoutError()} if cfg_calls["n"] <= 1 else {}

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, flaky, cfg=_CFG_DEAD):
            ok = await mgr.verify_connectivity()

        self.assertTrue(ok, "重检轮应通过")
        self.assertEqual(cfg_calls["n"], 2, "配置通道恰在两轮的第二次通过")

    async def test_auto_retry_both_fail(self) -> None:
        """自动档两轮皆败才定性失败"""
        from bot._managers._settings import SettingsManager

        mgr = SettingsManager(lambda: "tok")
        calls = {"n": 0}

        async def dead(token: str, proxy: str) -> dict:
            calls["n"] += 1
            return {
                _proxy_item(): _errors().ProxyConnectionRefusedError(proxy=_CFG_DEAD)
            }

        mod = sys.modules["bot._managers._settings"]
        with _patched(mod, dead, cfg=_CFG_DEAD):
            ok = await mgr.verify_connectivity()

        self.assertFalse(ok)
        self.assertEqual(calls["n"], 4, "两轮各两通道")
        self.assertIn("均无法连通", mgr.last_errors[_proxy_item()])

    async def test_auto_retry_reopens_table_with_hint(self) -> None:
        """重检轮重发整表刷掉首轮红行，头部带重测提示"""
        from unittest.mock import MagicMock

        from bot._managers._settings import SettingsManager
        from skin.messages import CheckMessage
        from utils.network import FrameKey

        mgr = SettingsManager(lambda: "tok")
        cfg_calls = {"n": 0}

        async def flaky(token: str, proxy: str) -> dict:
            if not proxy:
                return {_proxy_item(): _errors().DirectTimeoutError()}
            cfg_calls["n"] += 1
            return {_proxy_item(): ProbeTimeoutError()} if cfg_calls["n"] <= 1 else {}

        frames: list[dict] = []
        bridge = MagicMock()
        bridge.verify_progress.emit.side_effect = frames.append

        mod = sys.modules["bot._managers._settings"]
        with (
            _patched(mod, flaky, cfg=_CFG_DEAD),
            patch.object(mod, "gui_bridge", bridge),
        ):
            ok = await mgr.verify_connectivity()

        self.assertTrue(ok, "重检轮应通过")
        resets = [f for f in frames if FrameKey.ROWS in f]
        self.assertEqual(len(resets), 2, "重检轮应重发一次整表")
        retry = resets[1]
        self.assertEqual(retry.get(FrameKey.HEAD), CheckMessage.RETRY_HEAD)
        probed = [r for r in retry[FrameKey.ROWS] if r["id"] in ("cfg", "direct")]
        self.assertEqual(
            [r["status"] for r in probed],
            [CHECKING, CHECKING],
            "重检整表的待测通道行应全部刷回检测中",
        )
        self.assertTrue(all("budget" in r for r in probed), "重检行应重新装上计时预算")


@unittest.skipUnless(_ADAPTER_LOADED, "适配层未装载，整表铺送用例跳过")
class TestOpeningRows(unittest.TestCase):
    """回归点

    - 首帧整表只按计划排的行铺，结论行恒在表尾
    - 本地行只属校验轮，诊断轮不传本地帧即不出这行
    """

    def _plan(self, mode: str, cfg: str = "", sys_proxy: str | None = None):
        """按给定档位造一份计划"""
        return _plan_mod().build_connection_plan(
            {"proxy": {"proxy_mode": mode, "proxy": cfg}}, "tok", system_proxy=sys_proxy
        )

    def test_cfg_single_rows(self) -> None:
        """单路配置表只剩本路、本地与结论三行"""
        from utils.network import RowId, RowStatus, opening_rows

        rows = opening_rows(
            self._plan("cfg", _CFG_DEAD),
            local_frame={
                "id": RowId.LOCAL,
                "title": CheckMessage.ROW_LOCAL,
                "status": RowStatus.OK,
                "detail": "",
            },
        )
        self.assertEqual([r["id"] for r in rows], ["cfg", "local", "advice"])
        self.assertTrue(all("title" in r for r in rows), "整表每一行都要带标题")

    def test_no_local_frame_drops_local_row(self) -> None:
        """不传本地帧即不出本地行，诊断那一路靠这个"""
        from utils.network import RowId, opening_rows

        rows = opening_rows(self._plan("auto"))
        self.assertNotIn(RowId.LOCAL, [r["id"] for r in rows])

    def test_auto_rows_follow_plan_order(self) -> None:
        """自动档按配置、系统、直连排，缺席行直接给终态"""
        from utils.network import RowStatus, opening_rows

        rows = opening_rows(self._plan("auto"))
        self.assertEqual([r["id"] for r in rows], ["cfg", "sys", "direct", "advice"])
        self.assertEqual(rows[0]["status"], RowStatus.FAIL, "空配置行缺席")
        self.assertEqual(rows[1]["status"], RowStatus.FAIL, "无系统代理行缺席")
        self.assertEqual(rows[2]["status"], CHECKING, "直连行待测")


class TestEnumFieldValidation(unittest.TestCase):
    """回归点

    - 枚举字段非法值检出，合法值放行
    """

    def test_bad_mode_flagged(self) -> None:
        """模式值不在选项表即报错"""
        from dataclasses import replace

        from bot._managers._config_sources import config_sources
        from utils.config._schema import build_schema
        from utils.config._validator import validate_types
        from utils.config.sources import assemble

        with fake_adapter_parts():
            sections = assemble(config_sources()).sections
        proxy_tab = build_schema(sections)[0]
        mode_field = next(f for f in proxy_tab.fields if f.key == "proxy_mode")
        schema = [replace(proxy_tab, fields=[mode_field])]
        values = {"adapter.tg.proxy": {"proxy_mode": "tun"}}
        self.assertIn(proxy_tab.path_of(mode_field), validate_types(schema, values))
        self.assertEqual(
            validate_types(schema, {"adapter.tg.proxy": {"proxy_mode": "sys"}}), {}
        )


class TestStaleFrameDrain(unittest.TestCase):
    """回归点

    - 无窗轮次缓存的行帧在结论帧到达时作废
    - 过期行帧不得补播进下一轮窗口刷出假红
    """

    def test_drain_on_conclusion(self) -> None:
        """结论帧清缓存"""
        from unittest.mock import MagicMock

        from ui._windows._controllers._verify import VerifyCoordinator
        from utils.network import RowId, RowStatus

        mod = sys.modules["ui._windows._controllers._verify"]
        coord = VerifyCoordinator(MagicMock())
        with patch.object(mod, "current_check_window", return_value=None):
            coord.on_frame({"id": "cfg", "status": CHECKING})
            self.assertEqual(len(coord.pre_frames), 1, "无窗轮次应先缓存行帧")
            coord.on_frame({"id": RowId.ADVICE, "status": RowStatus.FAIL})
            self.assertEqual(coord.pre_frames, [], "结论帧应作废旧行帧")


class TestRoundWindowOpens(unittest.TestCase):
    """回归点

    - 起轮只挂中断标记，首个进度帧才开等待窗
    - 免测轮不发进度帧，窗口一次不开
    - 上轮收尾留下的常驻死窗不吃帧，新一轮照旧开窗补播
    """

    def _parts(self, stale: object = None) -> tuple[object, object, dict]:
        """造协调器与假窗

        - stale 非空即模拟上轮收尾后常驻的死窗
        """
        from unittest.mock import MagicMock

        from ui._windows._controllers._verify import VerifyCoordinator

        win = MagicMock()
        mod = sys.modules["ui._windows._controllers._verify"]
        opener = {"n": 0}

        def fake_open(_parent: object) -> MagicMock:
            opener["n"] += 1
            return win

        patch.object(mod, "current_check_window", return_value=stale).start()
        patch.object(mod, "open_check_window", fake_open).start()
        self.addCleanup(patch.stopall)
        return VerifyCoordinator(MagicMock()), win, opener

    def test_first_frame_opens_window(self) -> None:
        """整表帧到达才开窗"""
        from utils.network import FrameKey

        coord, win, opener = self._parts()

        self.assertTrue(coord.start_round(aborts=True))
        self.assertEqual(opener["n"], 0, "起轮不该立刻开窗")

        coord.on_frame({FrameKey.ROWS: [{"id": "cfg"}]})
        self.assertEqual(opener["n"], 1, "首个进度帧应拉起等待窗")
        win.begin_round.assert_called_once()

    def test_local_round_never_opens(self) -> None:
        """免测轮只有结论帧，不开窗"""
        from utils.network import RowId, RowStatus

        coord, _, opener = self._parts()

        self.assertTrue(coord.start_round(aborts=True))
        coord.on_frame({"id": RowId.ADVICE, "status": RowStatus.OK})

        self.assertEqual(opener["n"], 0, "免测轮不该开等待窗")
        self.assertEqual(coord.pre_frames, [], "结论帧应清空中转缓存")

    def test_stale_window_reopens(self) -> None:
        """上轮收尾的死窗改走重开，进度帧不落空"""
        from unittest.mock import MagicMock

        from ui._dialogs import Round
        from utils.network import FrameKey

        stale = MagicMock()
        stale.round = Round.VERIFY
        stale.is_running = False
        coord, win, opener = self._parts(stale=stale)

        self.assertTrue(coord.start_round(aborts=True))
        coord.on_frame({FrameKey.ROWS: [{"id": "cfg"}]})

        self.assertEqual(opener["n"], 1, "死窗不该顶掉新一轮的等待窗")
        win.begin_round.assert_called_once()
        stale.apply.assert_not_called()


class TestConclusionStaysAboveSetup(unittest.TestCase):
    """回归点

    - 诊断轮的检查窗也挂浮顶关系，强制向导后出场压不住结论
    - 窗已隐藏则不挂，不给常驻死窗逼出原生句柄
    """

    def _follow(self, win: object) -> tuple[object, object]:
        """按给定检查窗挂一次浮顶，返回面板宿主与浮顶桩"""
        from unittest.mock import MagicMock

        from ui._windows._controllers._verify import VerifyCoordinator

        mod = sys.modules["ui._windows._controllers._verify"]
        patch.object(mod, "current_check_window", return_value=win).start()
        self.addCleanup(patch.stopall)

        host = MagicMock()
        with patch.object(mod, "follow_above") as follow:
            VerifyCoordinator(host).follow_panel()
        return host, follow

    def test_diagnose_window_follows_panel(self) -> None:
        """非校验轮的在途窗同样交给浮顶件"""
        from unittest.mock import MagicMock

        from ui._dialogs import Round

        win = MagicMock()
        win.round = Round.DIAGNOSE
        host, follow = self._follow(win)

        follow.assert_called_once_with(win, host._panel)

    def test_hidden_window_skipped(self) -> None:
        """隐藏单例不吃浮顶"""
        from unittest.mock import MagicMock

        win = MagicMock()
        win.isVisible.return_value = False
        _, follow = self._follow(win)

        follow.assert_not_called()

    def test_no_window_no_binding(self) -> None:
        """无窗即返回，不碰宿主"""
        _, follow = self._follow(None)

        follow.assert_not_called()


class TestFollowAbove(unittest.TestCase):
    """回归点

    - 挂跟随关系同时补一层激活上浮，上浮只在激活事件发生
    - 同一面板重复调用不重复挂上浮钩子
    - 上浮只排先后，不抢被跟窗的焦点
    """

    def _owner(self) -> object:
        """造一只被跟的窗"""
        from unittest.mock import MagicMock

        return MagicMock()

    def test_bind_relation_and_lift(self) -> None:
        """关系挂上、钩子挂上、当场浮一次"""
        from unittest.mock import MagicMock

        from ui._primitives._stack import follow_above

        top = MagicMock()
        owner = self._owner()
        with patch("ui._primitives._stack.bring_front") as lifted:
            follow_above(top, owner)

        top.windowHandle().setTransientParent.assert_called_once_with(
            owner.windowHandle()
        )
        owner.installEventFilter.assert_called_once()
        lifted.assert_called_once_with(top, False, owner)

    def test_repeat_call_installs_one_lift(self) -> None:
        """同一只被跟窗不叠第二层钩子"""
        from unittest.mock import MagicMock

        from ui._primitives._stack import follow_above

        owner = self._owner()
        follow_above(MagicMock(), owner)
        follow_above(MagicMock(), owner)

        owner.installEventFilter.assert_called_once()

    def test_lift_reacts_to_activate_only(self) -> None:
        """激活事件上浮一次，别的事件不动"""
        from unittest.mock import MagicMock

        from PySide6.QtCore import QEvent, QObject

        from ui._primitives._stack import _LiftOnActivate

        top = MagicMock()
        lift = _LiftOnActivate(top)
        watched = QObject()
        lifted = patch("ui._primitives._stack.bring_front").start()
        self.addCleanup(patch.stopall)

        def send(kind: QEvent.Type) -> bool:
            """给钩子喂一只真事件，返回它是否吞下"""
            return lift.eventFilter(watched, QEvent(kind))

        self.assertFalse(send(QEvent.Type.Paint))
        lifted.assert_not_called()

        self.assertFalse(send(QEvent.Type.WindowActivate))
        lifted.assert_called_once_with(top, False, watched)


class TestLiftYieldsToOtherModal(unittest.TestCase):
    """回归点

    - 被跟窗自己模态不算拦路，结论窗照样浮
    - 只有别的模态窗开着才让位
    """

    def _front(self, modal: object, owner: object) -> object:
        """按「当前模态窗」与「被跟窗」各喂一次上浮，返回被提的窗"""
        from unittest.mock import MagicMock

        from ui._primitives._stack import bring_front

        top = MagicMock()
        top.isVisible.return_value = True
        with patch(
            "ui._primitives._stack.QApplication.activeModalWidget", return_value=modal
        ):
            bring_front(top, False, owner)
        return top

    def test_owner_modal_still_lifts(self) -> None:
        """被跟面板自己模态也照样浮"""
        panel = object()
        top = self._front(panel, panel)

        top.raise_.assert_called_once()

    def test_other_modal_blocks_lift(self) -> None:
        """别的模态窗开着则让位"""
        top = self._front(object(), object())

        top.raise_.assert_not_called()


class TestResultWindowOwner(unittest.TestCase):
    """结果窗该挂谁

    - 有模态窗开着就挂它，结果浮在它上面
    - 开着的已是报结果的窗时交回 None，等它关闭
    - 没有模态窗开着时挂回主窗
    """

    def _owner(self, modal: object, fallback: object) -> object:
        """按「当前那只模态窗」取结果窗的父"""
        from ui._windows import _main_window

        with patch.object(
            _main_window.QApplication, "activeModalWidget", return_value=modal
        ):
            return _main_window._result_owner(fallback)

    def test_parent_is_host_window(self) -> None:
        """开着的是普通模态窗就挂它"""
        from unittest.mock import MagicMock

        from ui._primitives import BaseDialog

        host = MagicMock(spec=BaseDialog)
        host.RESULT_WINDOW = False

        self.assertIs(self._owner(host, object()), host)

    def test_parent_is_main_window_when_free(self) -> None:
        """没有模态窗开着时挂回主窗"""
        main_window = object()

        self.assertIs(self._owner(None, main_window), main_window)

    def test_waits_for_result_window(self) -> None:
        """报结果的窗在场时交回 None，不叠第二只"""
        from unittest.mock import MagicMock

        from ui._dialogs import (
            NoticeDialog,
            PersonaResolveDialog,
            PersonaSyncDialog,
        )
        from ui._primitives import BaseDialog

        self.assertFalse(BaseDialog.RESULT_WINDOW)
        for window in (NoticeDialog, PersonaResolveDialog, PersonaSyncDialog):
            self.assertTrue(window.RESULT_WINDOW)

        modal = MagicMock(spec=NoticeDialog)
        modal.RESULT_WINDOW = True

        self.assertIsNone(self._owner(modal, object()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
