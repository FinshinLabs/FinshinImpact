"""网络连通诊断

- 适配器交出检查计划，本体按计划跑通用调度
- 全部通道失败给不通结论并标记断链
- 凭证探测与引擎预热由装配层交来
"""

from collections.abc import Callable, Coroutine
from typing import Any

from finshin_sdk import AdapterParts
from finshin_sdk.domain import ConnectionPlan
from skin.messages import CheckMessage

from .._config_manager import config_manager
from ..config import SourceKind, source_identity, source_values
from ..logger import get_logger
from ..network import (
    FrameKey,
    RowId,
    RowStatus,
    detect_system_proxy,
    opening_rows,
)
from ..paths import PLATFORM
from ._advice import failure_note
from ._verify import run_probe_round

# 诊断跑在后台线程的私有 loop，计时句走此器落 debug
_logger = get_logger("Mgr.Diagnose")


def _never_stop() -> bool:
    """默认停止回调"""
    return False


def _never_emit(_frame_data: dict) -> None:
    """无回调占位"""
    return None


def bind_diagnose(parts: AdapterParts) -> Callable[..., Coroutine[Any, Any, None]]:
    """绑上适配器交出的件后的诊断入口"""

    async def flow(
        token: str = "",
        emit: Callable[[dict], None] | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> None:
        values = source_values(
            source_identity(SourceKind.ADAPTER, str(PLATFORM)),
            parts.sections,
            config_manager.get_all(),
        )
        plan = parts.plan_for(values, token, system_proxy=detect_system_proxy())
        await diagnose_flow(
            plan,
            emit,
            stop_check,
            engine_preload=parts.engine_preload,
        )

    return flow


async def diagnose_flow(
    plan: ConnectionPlan,
    emit: Callable[[dict], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
    *,
    engine_preload: Callable[[], None],
) -> None:
    """执行一轮网络诊断

    - 只测计划里排定的通道，缺席行不发探测
    - 两轮都全挂才定不通，给不通结论并标记断链
    - 收到中止请求时取消在测任务，不输出结论
    """
    frame = emit or _never_emit
    stop = stop_check or _never_stop

    # 首帧把通道行点亮为检测中即启动界面倒计时，引擎导入费须在这之前付完
    engine_preload()
    frame({FrameKey.ROWS: opening_rows(plan)})

    def replay() -> None:
        """预热后重发整表清场"""
        _logger.debug(CheckMessage.RETRY_HEAD)
        frame(
            {
                FrameKey.ROWS: opening_rows(plan),
                FrameKey.HEAD: CheckMessage.RETRY_HEAD,
            }
        )

    outcome = await run_probe_round(plan.channels, frame, replay, stop)
    if stop():
        return

    if outcome.accepted is not None:
        frame(
            {
                "id": RowId.ADVICE,
                "status": RowStatus.OK,
                "detail": CheckMessage.ADVICE_OK,
            }
        )
        return

    verdict = plan.finish(outcome)
    frame(
        {
            "id": RowId.ADVICE,
            "status": RowStatus.FAIL,
            "detail": failure_note(verdict.failure_detail, verdict.field_errors),
            FrameKey.BROKEN: verdict.field_errors,
        }
    )
