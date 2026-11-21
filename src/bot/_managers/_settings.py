"""配置管理器

- 配置加载与连通性双重校验
- 字段级错误文案供向导标红
"""

import time
from collections.abc import Callable

from finshin_sdk import ConnectionPlan
from finshin_sdk.domain import ConfigPath
from skin.messages import CheckMessage
from ui import gui_bridge
from utils import config_manager
from utils.check import local_row, run_probe_round
from utils.config import (
    AppSchema,
    FieldErrors,
    ensure_config,
    get_schema,
    load_config,
    source_values,
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


def _label_of(schema: AppSchema, item: ConfigPath | str) -> str:
    """按配置项身份取界面标题"""
    for tab in schema:
        for fld in tab.fields:
            if tab.path_of(fld) == item:
                return fld.label
    return str(item)


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

        # 上次验证时的计划输入，变化判定基准
        self._net_key: object = None

    async def _execute(self) -> None:
        """加载配置进内存"""
        ensure_config(config_sources())
        config_manager.load(load_config())

    async def verify_connectivity(self) -> bool:
        """按字段变化分流的连通校验

        - 网络参数全未变、上轮连通通过且引擎不在断连周期时只跑本地校验
        - 通过则记录生效通道与连通结论
        - 计划与文案由适配器给，本体只跑通用调度
        """
        t0 = time.monotonic()
        schema = get_schema()
        parts = parts_for(PLATFORM)
        values = source_values(
            f"adapter.{PLATFORM}", parts.sections, config_manager.get_all()
        )
        plan = parts.plan_for(values, self._get_token(), detect_system_proxy())

        # 免测只认连通结论：计划输入一变旧结论就不作数，引擎正断线时更得重探
        down = link_report.snapshot().down
        if plan.reuse_key == self._net_key and self.link_verified and not down:
            return self._local_round(schema)
        self._net_key = plan.reuse_key

        # 起联网重探前先清旧结论：探测中途异常不该留下过时的连通账
        self.link_verified = False
        type_errors = self._emit_opening(plan, schema)
        outcome = await run_probe_round(
            plan.channels,
            gui_bridge.verify_progress.emit,
            lambda: self._emit_opening(plan, schema, head=CheckMessage.RETRY_HEAD),
        )
        verdict = plan.finish(outcome)
        resolved = outcome.accepted.effective if outcome.accepted else None
        self.resolved_proxy = resolved
        if verdict.notice:
            self.logger.info(verdict.notice)
        if verdict.warning:
            self.logger.error(verdict.warning)

        # 连通判据独立记：探到可用通道才算通，本地类型错不参与
        self.link_verified = resolved is not None
        self.last_errors = {**verdict.field_errors, **type_errors}
        self.logger.info(CheckMessage.ROUND_COST.format(cost=time.monotonic() - t0))
        return self._emit_advice(schema)

    def _local_round(self, schema: AppSchema) -> bool:
        """只跑本地校验的免测轮

        - 不发进度帧，秒过的轮次不占等待窗
        - 一个探测包都没发，只报免测不报用时
        """
        _, type_errors = local_row(schema, config_manager.get_all())
        self.last_errors = type_errors
        self.logger.info(CheckMessage.LOCAL_ONLY)
        return self._emit_advice(schema)

    def _emit_opening(
        self, plan: ConnectionPlan, schema: AppSchema, *, head: str = ""
    ) -> FieldErrors:
        """发送首帧进度整表

        - 本地校验结果随首帧先行显示，不等网络探测
        - head 非空即重发整表清场，已定案的红行不吃单行帧
        - 返回本地类型错误供后续结论合并
        """
        local_frame, type_errors = local_row(schema, config_manager.get_all())
        frame: dict = {FrameKey.ROWS: opening_rows(plan, local_frame)}
        if head:
            frame[FrameKey.HEAD] = head
            self.logger.debug(head)
        gui_bridge.verify_progress.emit(frame)
        return type_errors

    def _emit_advice(self, schema: AppSchema) -> bool:
        """发送结论帧

        - 失败只报数量，明细由字段标红与悬浮提示显示
        """
        passed = not self.last_errors
        gui_bridge.verify_progress.emit(
            {
                "id": RowId.ADVICE,
                "status": RowStatus.OK if passed else RowStatus.FAIL,
                "detail": (
                    CheckMessage.ADVICE_OK
                    if passed
                    else CheckMessage.VERIFY_ADVICE_FAIL.format(n=len(self.last_errors))
                ),
            }
        )
        if self.last_errors:
            fields = "、".join(_label_of(schema, k) for k in self.last_errors)
            self.logger.error(CheckMessage.FAIL.format(fields=fields))
        return passed
