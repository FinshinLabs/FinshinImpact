"""网络探测共享引擎

- 进度表协议键与首帧铺表
- 候选通道与探测预算由适配器的检查计划交出
"""

from typing import Any

from finshin_sdk import ConnectionPlan
from skin.messages import CheckMessage


class RowStatus:
    """表格行五态"""

    PENDING = "pending"
    CHECKING = "checking"
    OK = "ok"
    FAIL = "fail"
    SKIP = "skip"


class RowId:
    """进度表行协议串

    - 平台通道行的 id 由适配器计划自带，本体只认本地校验与结论两行
    """

    LOCAL = "local"
    ADVICE = "advice"


class FrameKey:
    """进度帧的键协议"""

    ROWS = "rows"
    HEAD = "head"
    BROKEN = "broken"


def opening_rows(
    plan: ConnectionPlan, local_frame: dict | None = None
) -> list[dict[str, Any]]:
    """生成检查轮整表首帧

    - 计划里的通道行标为检测中，缺席与去重行按计划直接给终态
    - 给本地校验结果才出本地行，诊断那一轮走的就是这一档
    - 结论行恒在表尾
    """
    channels = {channel.row_id: channel for channel in plan.channels}
    rows: list[dict[str, Any]] = []
    for row in plan.rows:
        item: dict[str, Any] = {
            "id": row.row_id,
            "title": row.title,
            "status": row.status,
            "detail": row.detail,
        }
        channel = channels.get(row.row_id)
        if channel is not None:
            item["status"] = RowStatus.CHECKING
            item["budget"] = int(channel.budget)
        rows.append(item)
    if local_frame is not None:
        rows.append(local_frame)
    rows.append(
        {
            "id": RowId.ADVICE,
            "title": CheckMessage.ROW_ADVICE,
            "status": RowStatus.PENDING,
            "detail": "",
        }
    )
    return rows


def verify_skeleton() -> list[dict]:
    """校验轮的等待态占位表

    - 计划未到时只铺本地与结论两行，首个整表帧到即换真表
    """
    return [
        {
            "id": RowId.LOCAL,
            "title": CheckMessage.ROW_LOCAL,
            "status": RowStatus.PENDING,
            "detail": "",
        },
        {
            "id": RowId.ADVICE,
            "title": CheckMessage.ROW_ADVICE,
            "status": RowStatus.PENDING,
            "detail": "",
        },
    ]


def probe_skeleton() -> list[dict]:
    """诊断轮的等待态占位表

    - 诊断不跑本地校验，首帧到即换真表
    """
    return [
        {
            "id": RowId.ADVICE,
            "title": CheckMessage.ROW_ADVICE,
            "status": RowStatus.PENDING,
            "detail": "",
        },
    ]
