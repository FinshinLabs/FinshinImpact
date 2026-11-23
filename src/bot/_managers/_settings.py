"""配置管理器

- 配置加载与连通性双重校验
- 保存轮加跑插件自己交的探测计划
- 字段级错误文案供向导标红
"""

import time
from collections.abc import Callable, Sequence

from finshin_sdk import ConnectionPlan, PlanVerdict
from finshin_sdk.domain import ConfigPath
from skin.messages import CheckMessage
from ui import gui_bridge
from utils import config_manager
from utils.check import local_row, run_probe_round
from utils.config import (
    AppSchema,
    FieldErrors,
    SourceKind,
    ensure_config,
    get_schema,
    load_config,
    owner_item,
    source_identity,
    source_values,
)
from utils.network import (
    FrameKey,
    RowId,
    RowStatus,
    detect_system_proxy,
    link_report,
)
from utils.paths import PLATFORM

from .._adapter_host import parts_for
from ._base import BaseManager
from ._config_sources import config_sources, enabled_plugin_declarations
from ._probe_frame import pending_rows, settled_rows, skipped_plan


def _label_of(schema: AppSchema, item: ConfigPath) -> str:
    """按配置项身份取界面标题"""
    for tab in schema:
        for fld in tab.fields:
            if tab.path_of(fld) == item:
                return fld.label
    return item.dotted


class SettingsManager(BaseManager):
    """配置加载与验证管理器

    - 加载配置、探测连通性
    - 校验失败的字段级错误留在本类清单，供向导标注
    """

    LOGGER_NAME = "Settings"

    def __init__(self, get_token: Callable[[], str]) -> None:
        """初始化配置管理器"""
        super().__init__()
        self._get_token = get_token

        # 最近一次验证失败：{配置项身份: 错误文案}，供向导标注字段
        self.last_errors: FieldErrors = {}

        # 三级解析出的生效通道，未通过为 None，空串表示直连
        self.resolved_proxy: str | None = None

        # 最近一轮网络探测的连通结论，与本地校验错身分开记
        self.link_verified = False

        self.last_failure_detail = ""
        self.last_fatal = False

        # 上次验证时的计划输入，变化判定基准
        self._net_key: object = None

        # 插件探测的免测基准：上次免测键与上轮是否通过
        self._plugin_keys: dict[str, object] = {}
        self._plugin_ok: set[str] = set()

    async def _execute(self) -> None:
        """加载配置进内存"""
        ensure_config(config_sources())
        config_manager.load(load_config())
        if owner_item() is None:
            self.logger.info("配置里没有标 owner 的字段，主人档保持空白")

    async def verify_connectivity(self, from_candidate: bool = False) -> bool:
        """按字段变化分流的连通校验

        - 网络参数全未变、上轮连通通过且引擎不在断连周期时只跑本地校验
        - 保存轮再跑插件交的探测，启动轮一律不跑，平台那轮先于插件那轮，行并进同一张表
        """
        t0 = time.monotonic()
        self.last_failure_detail = ""
        self.last_fatal = False
        schema = get_schema()
        parts = parts_for(PLATFORM)
        identity = source_identity(SourceKind.ADAPTER, str(PLATFORM))
        values = source_values(identity, parts.sections, config_manager.get_all())
        plan = parts.plan_for(
            values, self._get_token(), system_proxy=detect_system_proxy()
        )
        local_frame, type_errors = local_row(schema, config_manager.get_all())
        rounds = self._plugin_rounds(type_errors) if from_candidate else ()
        runnable = tuple((name, item) for name, item in rounds if item.channels)

        # 免测只认连通结论：计划输入一变旧结论就不作数，引擎正断线时更得重探
        down = link_report.snapshot().down
        free = plan.reuse_key == self._net_key and self.link_verified and not down
        if free and not runnable:
            return self._local_round(schema)
        if not free:
            self._net_key = plan.reuse_key
            self.link_verified = False

        plans: list[ConnectionPlan] = [item for _, item in rounds]
        if not free:
            plans.insert(0, plan)
        self._emit_frame(plans, local_frame)

        verdict = PlanVerdict()
        settled: dict[str, tuple[str, str]] = {}
        if not free:
            outcome = await run_probe_round(
                plan.channels,
                gui_bridge.verify_progress.emit,
                lambda: self._emit_frame(
                    plans, local_frame, head=CheckMessage.RETRY_HEAD
                ),
            )
            verdict = plan.finish(outcome)
            resolved = outcome.accepted.effective if outcome.accepted else None
            self.resolved_proxy = resolved
            self.link_verified = resolved is not None
            settled = settled_rows(plan, outcome)
            self._remember_verdict(verdict)
            self._log_verdict(verdict)

        plugin_errors = await self._run_plugin_rounds(
            runnable, plans, local_frame, settled
        )
        self.last_errors = {**verdict.field_errors, **plugin_errors, **type_errors}
        self.logger.info(CheckMessage.ROUND_COST.format(cost=time.monotonic() - t0))
        return self._emit_advice(schema)

    async def _run_plugin_rounds(
        self,
        runnable: Sequence[tuple[str, ConnectionPlan]],
        plans: list[ConnectionPlan],
        local_frame: dict,
        settled: dict[str, tuple[str, str]],
    ) -> FieldErrors:
        """逐个跑插件交的探测并记下结论"""
        plugin_errors: FieldErrors = {}
        for name, item in runnable:
            outcome = await run_probe_round(
                item.channels,
                gui_bridge.verify_progress.emit,
                lambda: self._emit_frame(
                    plans,
                    local_frame,
                    head=CheckMessage.RETRY_HEAD,
                    settled={**settled},
                ),
            )
            plugin_verdict = item.finish(outcome)
            plugin_errors.update(plugin_verdict.field_errors)
            self._remember_verdict(plugin_verdict)
            self._log_verdict(plugin_verdict)
            self._plugin_keys[name] = item.reuse_key
            if outcome.accepted is not None:
                self._plugin_ok.add(name)
            else:
                self._plugin_ok.discard(name)
            settled.update(settled_rows(item, outcome))
        return plugin_errors

    def _plugin_rounds(
        self, type_errors: FieldErrors
    ) -> tuple[tuple[str, ConnectionPlan], ...]:
        """按保存轮候选值装配插件探测计划

        - 本地已有类型错、不交计划或计划为空的来源都不探测
        - 值没变且上轮通过的直接给绿灯行，不发请求
        """
        rounds: list[tuple[str, ConnectionPlan]] = []
        for name, declared in enabled_plugin_declarations():
            if declared.probe is None:
                continue
            source = source_identity(SourceKind.PLUGIN, name)
            if any(item.source == source for item in type_errors):
                continue
            try:
                plan = declared.probe(
                    source_values(source, declared.sections, config_manager.get_all())
                )
            except Exception as e:
                self.logger.send_error(f"插件 {name} 探测计划造不出来", e)
                continue
            if plan is None:
                continue
            if (
                plan.reuse_key == self._plugin_keys.get(name)
                and name in self._plugin_ok
            ):
                plan = skipped_plan(plan)
            rounds.append((name, plan))
        return tuple(rounds)

    def _emit_frame(
        self,
        plans: Sequence[ConnectionPlan],
        local_frame: dict,
        *,
        head: str = "",
        settled: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        """发送首帧进度整表

        - 本地校验结果随首帧先行显示，不等网络探测
        - settled 里的行按已有终态上屏，供后续探针重发整表清场
        """
        rows: list[dict] = []
        for plan in plans:
            rows.extend(pending_rows(plan))
        for item in rows:
            if settled and item["id"] in settled:
                item["status"], item["detail"] = settled[item["id"]]
        rows.append(local_frame)
        rows.append(
            {
                "id": RowId.ADVICE,
                "title": CheckMessage.ROW_ADVICE,
                "status": RowStatus.PENDING,
                "detail": "",
            }
        )
        frame: dict = {FrameKey.ROWS: rows}
        if head:
            frame[FrameKey.HEAD] = head
            self.logger.debug(head)
        gui_bridge.verify_progress.emit(frame)

    def _remember_verdict(self, verdict: PlanVerdict) -> None:
        """记下结论句与致命旗

        - 非空结论句只留先到的一句，致命旗一旦为真即保持
        """
        if not self.last_failure_detail and verdict.failure_detail:
            self.last_failure_detail = verdict.failure_detail
        self.last_fatal = self.last_fatal or verdict.fatal

    def _log_verdict(self, verdict: PlanVerdict) -> None:
        """把裁决里的日志句写进日志"""
        if verdict.notice:
            self.logger.info(verdict.notice)
        if verdict.warning:
            self.logger.error(verdict.warning)

    def _local_round(self, schema: AppSchema) -> bool:
        """只跑本地校验的免测轮

        - 不发进度帧，秒过的轮次不占等待窗
        - 一个探测包都没发，只报免测不报用时
        """
        _, type_errors = local_row(schema, config_manager.get_all())
        self.last_errors = type_errors
        self.last_failure_detail = ""
        self.last_fatal = False
        self.logger.info(CheckMessage.LOCAL_ONLY)
        return self._emit_advice(schema)

    def _emit_advice(self, schema: AppSchema) -> bool:
        """发送结论帧

        - 失败优先用结论句，没有才报字段数量
        - 明细由字段标红与悬浮提示显示
        """
        passed = not self.last_errors
        gui_bridge.verify_progress.emit(
            {
                "id": RowId.ADVICE,
                "status": RowStatus.OK if passed else RowStatus.FAIL,
                "detail": (
                    CheckMessage.ADVICE_OK
                    if passed
                    else self.last_failure_detail
                    or CheckMessage.VERIFY_ADVICE_FAIL.format(n=len(self.last_errors))
                ),
            }
        )
        if self.last_errors:
            fields = "、".join(_label_of(schema, k) for k in self.last_errors)
            self.logger.error(CheckMessage.FAIL.format(fields=fields))
        return passed
