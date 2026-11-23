"""连通校验公共核心

- 全部通道并发探测，按优先级顺序取首个成功的通道
- 首轮全挂则预热后重跑一轮再定性
- 每轮逐档记耗时、上限与跳过，只落调试日志
"""

import asyncio
from collections.abc import Callable, Sequence

from finshin_sdk import ProbeChannel, ProbeOutcome, ProbeResult
from skin.messages import CheckMessage

from ..config import AppConfigData, AppSchema, FieldErrors, validate_types
from ..logger import get_logger
from ..network import CHECKING, RowId, RowStatus

_logger = get_logger("Check")

# 首轮全挂后的预热重检
_RETRY_WARMUP = 1.5  # 秒，等代理软件把 TUN 内核与监听拉起来再原样重跑

_EmitCallback = Callable[[dict], None]
_StopCheckCallback = Callable[[], bool]
_ReplayCallback = Callable[[], object]  # 重发整表清场的回调，返回值不吃


def _never_stop() -> bool:
    """默认停止回调"""
    # 永不中断
    return False


def _probe_tag(round_no: int, channel: ProbeChannel, started: float) -> str:
    """通道耗时行"""
    cost = asyncio.get_running_loop().time() - started
    return (
        f"探测第{round_no}轮 {channel.row_id} 跑了 {cost:.1f}s"
        f" 上限 {channel.budget:.1f}s"
    )


async def _probe_safe(channel: ProbeChannel, round_no: int) -> ProbeResult:
    """执行单通道探针

    - 探针异常记为该通道失败，不上抛
    - 耗时与终局逐行落调试日志
    """
    started = asyncio.get_running_loop().time()
    try:
        result = await channel.run()
    except asyncio.CancelledError:
        _logger.debug(f"{_probe_tag(round_no, channel, started)} 未采用 跳过")
        raise
    except Exception:
        _logger.debug(
            f"{_probe_tag(round_no, channel, started)} 探针异常", exc_info=True
        )
        result = ProbeResult(accepted=False, detail=CheckMessage.SELF_CRASH)
    state = "过" if result.accepted else f"不通 {result.detail}"
    _logger.debug(f"{_probe_tag(round_no, channel, started)} {state}")
    return result


def _settle_frame(channel: ProbeChannel, result: ProbeResult) -> dict:
    """组装单行终态帧

    - 展示句留空时按通道名统一生成成败文案
    """
    text = result.detail or CheckMessage.REACH.format(
        via=channel.label,
        state=CheckMessage.REACH_OK if result.accepted else CheckMessage.REACH_FAIL,
    )
    return {
        "id": channel.row_id,
        "status": RowStatus.OK if result.accepted else RowStatus.FAIL,
        "detail": text,
    }


async def _run_channels(
    channels: Sequence[ProbeChannel],
    round_no: int,
    emit: _EmitCallback,
    stop_check: _StopCheckCallback | None = None,
) -> ProbeOutcome:
    """并发探测全部通道

    - 全部通道先标为检测中
    - 高优先级未出结果时，低优先级的成功不提前采用
    - 选定后取消其余探测，未采用的标为跳过
    - 收到中止请求时整轮停下，不发终态帧
    """
    stop = stop_check or _never_stop
    order = list(channels)
    if not order:
        return ProbeOutcome()
    for channel in order:
        emit({"id": channel.row_id, "status": CHECKING, "detail": ""})

    tasks = {
        asyncio.ensure_future(_probe_safe(channel, round_no)): channel
        for channel in order
    }
    pending = set(tasks)
    results: dict[str, ProbeResult] = {}
    winner: ProbeChannel | None = None
    while pending and winner is None:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        if stop():
            break
        for task in done:
            channel = tasks[task]
            result = task.result()
            results[channel.row_id] = result

            # 败行即时落红：✗ 是终局，不会被清场翻案
            if not result.accepted:
                emit(_settle_frame(channel, result))

        # 按阶梯顺序走账：首个未交代处停下等它，已交代的位子里出现可走即定案
        for channel in order:
            result = results.get(channel.row_id)
            if result is None:
                break
            if result.accepted:
                winner = channel

                # 定案的绿勾此刻才上屏：按住期间它从没亮过，不存在翻案
                emit(_settle_frame(channel, result))
                break

    # 清场：在途陪跑取消，按住未发的成功者与未完成者统一补绿色带过
    stragglers = {task for task in tasks if not task.done()}
    for task in stragglers:
        task.cancel()
    if winner is not None:
        for channel in order:
            if channel is winner:
                continue
            result = results.get(channel.row_id)
            if result is None or result.accepted:
                emit(
                    {
                        "id": channel.row_id,
                        "status": RowStatus.SKIP,
                        "detail": CheckMessage.SKIP,
                    }
                )
    if stragglers:
        await asyncio.wait(stragglers)

    completed = tuple(
        (channel.row_id, results[channel.row_id])
        for channel in order
        if channel.row_id in results
    )
    if winner is None:
        return ProbeOutcome(results=completed)
    return ProbeOutcome(
        accepted=results[winner.row_id],
        accepted_row=winner.row_id,
        results=completed,
    )


async def run_probe_round(
    channels: Sequence[ProbeChannel],
    emit: _EmitCallback,
    replay: _ReplayCallback,
    stop_check: _StopCheckCallback | None = None,
) -> ProbeOutcome:
    """全挂则预热重跑的一轮通道探测

    - 重跑前重发整表清场，已定案的失败行不吃单行帧
    - 通道表为空或轮次被中止时不重跑
    """
    outcome = await _run_channels(channels, 1, emit, stop_check)
    stopped = stop_check is not None and stop_check()
    if outcome.accepted is not None or not channels or stopped:
        return outcome

    # 首轮全挂多为冷启动握手慢：歇一拍等内核拉起来，再趁热重检一轮定性
    _logger.debug(f"探测首轮全不通 预热 {_RETRY_WARMUP}s 后重跑第二轮")
    await asyncio.sleep(_RETRY_WARMUP)
    replay()
    return await _run_channels(channels, 2, emit, stop_check)


def local_row(schema: AppSchema, config: AppConfigData) -> tuple[dict, FieldErrors]:
    """本地配置校验

    - 交回本地行的终态帧与类型错误字典
    - 结果并入整表首帧先行显示，不等网络探测
    """
    errors = validate_types(schema, config)
    frame = {
        "id": RowId.LOCAL,
        "title": CheckMessage.ROW_LOCAL,
        "status": RowStatus.OK if not errors else RowStatus.FAIL,
        "detail": (
            CheckMessage.VERIFY_LOCAL_OK
            if not errors
            else CheckMessage.VERIFY_LOCAL_FAIL.format(n=len(errors))
        ),
    }
    return frame, errors
