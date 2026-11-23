"""探测进度表

- 计划初态与整表重发
- 一轮结果翻转成各行终态
"""

from finshin_sdk import ConnectionPlan, ProbeOutcome, ProbeRow
from skin.messages import CheckMessage
from utils.network import CHECKING, RowStatus


def pending_rows(plan: ConnectionPlan) -> list[dict]:
    """计划里各行的检测中初态"""
    channels = {channel.row_id: channel for channel in plan.channels}
    rows: list[dict] = []
    for row in plan.rows:
        item: dict = {
            "id": row.row_id,
            "title": row.title,
            "status": row.status,
            "detail": row.detail,
        }
        channel = channels.get(row.row_id)
        if channel is not None:
            item["status"] = CHECKING
            item["budget"] = int(channel.budget)
        rows.append(item)
    return rows


def settled_rows(
    plan: ConnectionPlan, outcome: ProbeOutcome
) -> dict[str, tuple[str, str]]:
    """把一轮结果翻成各行终态

    - 未出结果的通道按陪跑跳过，缺席行照计划原样
    """
    results = dict(outcome.results)
    channels = {channel.row_id: channel for channel in plan.channels}
    settled: dict[str, tuple[str, str]] = {}
    for row in plan.rows:
        channel = channels.get(row.row_id)
        if channel is None:
            settled[row.row_id] = (row.status, row.detail)
            continue
        result = results.get(row.row_id)
        if result is None:
            settled[row.row_id] = (RowStatus.SKIP, CheckMessage.SKIP)
            continue
        detail = result.detail or CheckMessage.REACH.format(
            via=channel.label,
            state=(
                CheckMessage.REACH_OK if result.accepted else CheckMessage.REACH_FAIL
            ),
        )
        settled[row.row_id] = (
            RowStatus.OK if result.accepted else RowStatus.FAIL,
            detail,
        )
    return settled


def skipped_plan(plan: ConnectionPlan) -> ConnectionPlan:
    """把免测计划改成绿灯行

    - 不发请求，只留上轮结论
    """
    return ConnectionPlan(
        rows=tuple(
            ProbeRow(
                row_id=row.row_id,
                title=row.title,
                status=RowStatus.OK,
                detail=CheckMessage.PLUGIN_SKIP,
            )
            for row in plan.rows
        ),
        channels=(),
        reuse_key=plan.reuse_key,
        finish=plan.finish,
    )
