"""AI 接口探测

- 保存轮发一次最小对话请求
- 失败按状态码翻成字段错，连不上只红行
"""

from exceptions import ConnectionFailedError, HTTPStatusError, RequestTimeoutError
from finshin_sdk import (
    ConnectionPlan,
    PlanVerdict,
    ProbeChannel,
    ProbeOutcome,
    ProbeResult,
    ProbeRow,
)
from finshin_sdk.domain import ConfigPath
from utils import get_logger

from .config import AIKey, AISection, ai_config
from .core import AIClient

_logger = get_logger("Plg.AI.Probe")

# 进度表那一行
_ROW_ID = "ai"
_ROW_TITLE = "AI 接口"

# 探测预算与说明长度
_BUDGET = 20.0
_DETAIL_LIMIT = 200

# 本插件来源码
_SOURCE = "plugin.AI"


def _item(key: AIKey) -> ConfigPath:
    """本插件配置项的完整身份"""
    return ConfigPath(source=_SOURCE, section=AISection.MODEL, key=key)


def _clip(text: str) -> str:
    """正文截到说明长度"""
    body = " ".join(text.split())
    return body[:_DETAIL_LIMIT]


async def _run() -> ProbeResult:
    """发一次最小对话请求

    - 只有 200 算通过，状态码按字段归类
    - 超时与连不上只红行，不指认字段
    """
    try:
        await AIClient.chat_once([{"role": "user", "content": "ping"}], 1)
    except HTTPStatusError as e:
        return _http_failure(e)
    except RequestTimeoutError:
        return ProbeResult(accepted=False, detail="请求超时")
    except ConnectionFailedError:
        return ProbeResult(accepted=False, detail="连不上接口")
    except Exception as e:
        return ProbeResult(accepted=False, detail=_clip(str(e)) or "请求失败")
    return ProbeResult(accepted=True)


def _http_failure(err: HTTPStatusError) -> ProbeResult:
    """按状态码与正文指认字段"""
    detail = f"{err.status_code} {_clip(err.msg)}".strip()
    if err.status_code in (401, 403):
        return ProbeResult(
            accepted=False,
            detail=detail,
            field_errors={_item(AIKey.API_KEY): f"密钥被接口拒绝（{err.status_code}）"},
        )
    if err.status_code == 404:
        return ProbeResult(
            accepted=False,
            detail=detail,
            field_errors={_item(AIKey.BASE_URL): "接口地址不存在（404）"},
        )
    if err.status_code == 400 and "model" in err.msg.lower():
        return ProbeResult(
            accepted=False,
            detail=detail,
            field_errors={_item(AIKey.MODEL): "接口不认这个模型名（400）"},
        )
    return ProbeResult(accepted=False, detail=detail)


def _finish(outcome: ProbeOutcome) -> PlanVerdict:
    """收一轮探测结果"""
    if outcome.accepted is not None:
        return PlanVerdict(notice=f"{_ROW_TITLE}可用")

    for _, result in outcome.results:
        if result.field_errors:
            return PlanVerdict(
                field_errors=dict(result.field_errors),
                failure_detail=result.detail,
            )
    detail = next((r.detail for _, r in outcome.results if r.detail), "")
    return PlanVerdict(failure_detail=detail)


def build_probe() -> ConnectionPlan:
    """造一份 AI 接口探测计划

    - 一行一通道，预算 20 秒
    - 复用键含地址、密钥与模型名
    """
    return ConnectionPlan(
        rows=(ProbeRow(row_id=_ROW_ID, title=_ROW_TITLE),),
        channels=(
            ProbeChannel(
                row_id=_ROW_ID,
                label=_ROW_TITLE,
                budget=_BUDGET,
                run=_run,
            ),
        ),
        reuse_key=(
            ai_config.base_url.strip(),
            ai_config.api_key.strip(),
            ai_config.model_name.strip(),
        ),
        finish=_finish,
    )
