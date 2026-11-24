"""配置管理器

- 配置加载与连通性双重校验
- 字段级错误文案供向导标红
"""

import time
from collections.abc import Callable

from finshin_sdk.domain import ConfigPath, ConnectionPlan, PlanVerdict
from skin.messages import CheckMessage
from ui import gui_bridge
from utils import config_manager
from utils.check import failure_note, local_row, run_probe_round
from utils.config import (
    AppSchema,
    FieldErrors,
    ProbeRecord,
    SourceKind,
    ensure_config,
    get_schema,
    load_config,
    owner_item,
    source_identity,
    source_values,
    validate_types,
)
from utils.network import (
    FrameKey,
    RowId,
    RowStatus,
    detect_system_proxy,
    link_report,
    opening_rows,
)
from utils.paths import PLATFORM

from .._adapter_host import parts_for
from ._base import BaseManager
from ._config_sources import config_sources


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

        self.last_probe: ProbeRecord | None = None

    async def _execute(self) -> None:
        """加载配置进内存"""
        ensure_config(config_sources())
        config_manager.load(load_config())
        if owner_item() is None:
            self.logger.info("配置里没有标 owner 的字段，主人档保持空白")

    async def verify_connectivity(
        self,
        *,
        group: str | None = None,
        probes: dict[str, ProbeRecord] | None = None,
    ) -> bool:
        """按字段变化分流的连通校验

        - 网络参数全未变、上轮连通通过且引擎不在断连周期时只跑本地校验
        - 给了来源即只校验本来源，适配器按本类计划单独检测
        """
        t0 = time.monotonic()
        self.last_failure_detail = ""
        self.last_fatal = False
        self.last_probe = None
        records = probes or {}
        schema = get_schema()
        parts = parts_for(PLATFORM)
        identity = source_identity(SourceKind.ADAPTER, str(PLATFORM))
        if group is not None and group != identity:
            return self._local_round(schema, group)

        values = source_values(identity, parts.sections, config_manager.get_all())
        plan = parts.plan_for(
            values, self._get_token(), system_proxy=detect_system_proxy()
        )
        record = records.get(identity)
        if group is None and record is not None and record.reuse_key == plan.reuse_key:
            return self._reuse_probe(schema, identity, plan, record)

        local_frame, type_errors = local_row(
            schema,
            config_manager.get_all(),
            group=identity if group is not None else None,
        )

        # 单类保存与复验必须重跑本类检测，整份启动才允许复用上次连通结论
        down = link_report.snapshot().down
        free = (
            group is None
            and plan.reuse_key == self._net_key
            and self.link_verified
            and not down
        )
        if free:
            return self._local_round(schema)
        self._net_key = plan.reuse_key
        self.link_verified = False

        self._emit_frame(plan, local_frame)

        outcome = await run_probe_round(
            plan.channels,
            gui_bridge.verify_progress.emit,
            lambda: self._emit_frame(plan, local_frame, head=CheckMessage.RETRY_HEAD),
        )
        verdict = plan.finish(outcome)
        resolved = outcome.accepted.effective if outcome.accepted else None
        self.resolved_proxy = resolved
        self.link_verified = resolved is not None
        self.last_probe = ProbeRecord(plan.reuse_key, resolved)
        self._remember_verdict(verdict)
        self._log_verdict(verdict)

        self.last_errors = {**verdict.field_errors, **type_errors}
        self.logger.info(CheckMessage.ROUND_COST.format(cost=time.monotonic() - t0))
        return self._emit_advice(schema)

    def _reuse_probe(
        self,
        schema: AppSchema,
        identity: str,
        plan: ConnectionPlan,
        record: ProbeRecord,
    ) -> bool:
        """复用指纹一致的检测记录，只校验适配器本类"""
        self._net_key = plan.reuse_key
        self.resolved_proxy = record.resolved_proxy
        self.link_verified = record.resolved_proxy is not None
        self.last_probe = record
        self.last_errors = validate_types(
            schema, config_manager.get_all(), group=identity
        )
        self.logger.info(f"来源 {identity} 复用本场检测记录")
        return self._emit_advice(schema)

    def _emit_frame(
        self,
        plan: ConnectionPlan,
        local_frame: dict,
        *,
        head: str = "",
    ) -> None:
        """发送首帧进度整表

        - 本地校验结果随首帧先行显示，不等网络探测
        """
        frame: dict = {FrameKey.ROWS: opening_rows(plan, local_frame)}
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

    def _local_round(self, schema: AppSchema, group: str | None = None) -> bool:
        """只跑本地校验的免测轮

        - 不发进度帧，秒过的轮次不占等待窗
        - 一个探测包都没发，只报免测不报用时
        """
        _, type_errors = local_row(schema, config_manager.get_all(), group=group)
        self.last_errors = type_errors
        self.last_failure_detail = ""
        self.last_fatal = False
        self.logger.info(CheckMessage.LOCAL_ONLY)
        return self._emit_advice(schema)

    def _emit_advice(self, schema: AppSchema) -> bool:
        """发送结论帧

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
                    else failure_note(self.last_failure_detail, self.last_errors)
                ),
            }
        )
        if self.last_errors:
            fields = "、".join(_label_of(schema, k) for k in self.last_errors)
            self.logger.error(CheckMessage.FAIL.format(fields=fields))
        return passed
