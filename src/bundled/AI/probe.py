"""AI 接口探测

- 检测一次发一次最小对话请求
- 失败把状态码与原始正文写进详情，能排除地址和密钥时再指认模型
- 排除不了就整表标红，结论行只给整表结论
"""

import json
from typing import Any

from exceptions import (
    ConnectionFailedError,
    HTTPBodyError,
    HTTPStatusError,
    RequestTimeoutError,
    describe_error,
)
from finshin_sdk.domain import (
    ConfigPath,
    ConfigValues,
    ConnectionPlan,
    PlanVerdict,
    ProbeChannel,
    ProbeOutcome,
    ProbeResult,
    ProbeRow,
)
from utils.logger import get_logger

from .config import SOURCE, PluginKeys, PluginSections
from .core import AIClient

_logger = get_logger("Plg.AI.Probe")

# 进度表那一行
_ROW_ID = "ai"
_ROW_TITLE = "AI 接口"

# 探测预算
_BUDGET = 20.0

# 2xx 却不是 JSON：多半地址指到了网页或网关
_FORMAT_ERROR = "接口返回的内容不是预期的格式，请检查地址"

# 消息列表里认得出的状态码
_KEY_CODES = (401, 403)
_MISSING_CODE = 404
_LIMIT_CODES = (402, 429)

# 地址和密钥已通，剩下只有模型这一项
_MODEL_NOTE = "地址和 Key 已通，问题多半在模型"

# 排除不了地址和密钥时的整表提示
_UNKNOWN_FIELD = "不知道是哪项配置出错"
_UNKNOWN_NOTE = "不知道是哪项配置出错，请看上面的返回"

# 连不上时指向地址字段
_TIMEOUT_NOTE = "请求超时，请检查地址"
_CONNECT_NOTE = "连不上接口，请检查地址"


def _item(key: PluginKeys) -> ConfigPath:
    """本插件配置项的完整身份"""
    return ConfigPath(source=SOURCE, section=PluginSections.MODEL, key=key)


def _text(values: ConfigValues, key: PluginKeys) -> str:
    """取表单里这一项的文本值"""
    section = values.get(PluginSections.MODEL) or {}
    raw = section.get(key)
    return raw.strip() if isinstance(raw, str) else ""


def _raw(status_code: int, body: str) -> str:
    """状态码与正文拼成一行原文"""
    return f"HTTP {status_code} {body}".strip()


def _body_text(body: Any) -> str:
    """2xx 正文原样转成文本"""
    try:
        return json.dumps(body, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(body)


def _field_failure(key: PluginKeys, message: str, detail: str) -> ProbeResult:
    """字段提示落配置项，原文落行上"""
    return ProbeResult(
        accepted=False, detail=detail, field_errors={_item(key): message}
    )


def _unknown_failure(detail: str) -> ProbeResult:
    """排除不了就把三项一起标红，原文留在行上"""
    note = _UNKNOWN_FIELD
    return ProbeResult(
        accepted=False,
        detail=detail,
        field_errors={
            _item(PluginKeys.BASE_URL): note,
            _item(PluginKeys.API_KEY): note,
            _item(PluginKeys.MODEL): note,
        },
    )


def _judge(body: Any) -> ProbeResult:
    """按 2xx 正文的形状定成败

    - 正文带 error 算失败
    - choices 非空，或只有 usage 的推理末帧，都算通过
    """
    if not isinstance(body, dict) or body.get("error"):
        return ProbeResult(accepted=False, detail=_body_text(body))
    if body.get("choices") or body.get("usage"):
        return ProbeResult(accepted=True)
    return ProbeResult(accepted=False, detail=_body_text(body))


async def _exclude_address_key(detail: str, base_url: str, api_key: str) -> ProbeResult:
    """补一次模型列表，能通就说明地址和密钥已通

    - 列表也通，剩余失败多半在模型
    - 列表报密钥或地址错，按它指认
    - 列表也说不清，三项一起标红
    """
    try:
        body = await AIClient.list_models(base_url, api_key)
    except HTTPStatusError as e:
        combined = f"{detail}\n{_raw(e.status_code, e.msg)}"
        if e.status_code in _KEY_CODES:
            return _field_failure(
                PluginKeys.API_KEY, f"密钥被接口拒绝（{e.status_code}）", combined
            )
        if e.status_code == _MISSING_CODE:
            return _field_failure(
                PluginKeys.BASE_URL, f"接口地址或路径不对（{e.status_code}）", combined
            )
        return _unknown_failure(combined)
    except RequestTimeoutError:
        return _field_failure(PluginKeys.BASE_URL, _TIMEOUT_NOTE, detail)
    except ConnectionFailedError:
        return _field_failure(PluginKeys.BASE_URL, _CONNECT_NOTE, detail)
    except HTTPBodyError as e:
        return _unknown_failure(f"{detail}\n{e.body}")
    except Exception as e:
        _logger.debug(f"模型列表探测抛出表外的错：{type(e).__name__}")
        return _unknown_failure(detail)

    if isinstance(body, dict) and body.get("error"):
        return _unknown_failure(f"{detail}\n{_body_text(body)}")
    return _field_failure(PluginKeys.MODEL, _MODEL_NOTE, detail)


async def _classify_http(
    err: HTTPStatusError, base_url: str, api_key: str
) -> ProbeResult:
    """按状态码先分走能确定的，剩下的再补模型列表"""
    detail = _raw(err.status_code, err.msg)
    if err.status_code in _KEY_CODES:
        return _field_failure(
            PluginKeys.API_KEY, f"密钥被接口拒绝（{err.status_code}）", detail
        )
    if err.status_code == _MISSING_CODE:
        return _field_failure(
            PluginKeys.BASE_URL, f"接口地址或路径不对（{err.status_code}）", detail
        )
    if err.status_code in _LIMIT_CODES:
        return ProbeResult(accepted=False, detail=detail)
    return await _exclude_address_key(detail, base_url, api_key)


async def _run(base_url: str, api_key: str, model: str) -> ProbeResult:
    """发一次最小对话请求

    - 状态码、超时与连不上先按字段分
    - 2xx 正文不是 JSON 归接口地址错，原文留在行上
    - 说不清的失败补一次模型列表，再决定是否指认模型
    """
    try:
        body = await AIClient.probe(
            [{"role": "user", "content": "ping"}],
            1,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )
    except HTTPStatusError as e:
        return await _classify_http(e, base_url, api_key)
    except HTTPBodyError as e:
        return _field_failure(PluginKeys.BASE_URL, _FORMAT_ERROR, e.body)
    except RequestTimeoutError:
        return _field_failure(
            PluginKeys.BASE_URL, _TIMEOUT_NOTE, describe_error(RequestTimeoutError())
        )
    except ConnectionFailedError:
        return _field_failure(PluginKeys.BASE_URL, _CONNECT_NOTE, "连不上接口")
    except Exception as e:
        _logger.debug(f"接口探测抛出表外的错：{type(e).__name__}")
        return ProbeResult(accepted=False, detail="请求失败")

    result = _judge(body)
    if result.accepted:
        return result
    return await _exclude_address_key(result.detail, base_url, api_key)


def _finish(outcome: ProbeOutcome) -> PlanVerdict:
    """收一轮探测结果

    - 失败只交标红的配置项，结论句归本体
    - 三项全红时换一句不知道是哪项错
    """
    if outcome.accepted is not None:
        return PlanVerdict(notice=f"{_ROW_TITLE}可用")
    for _, result in outcome.results:
        if len(result.field_errors) >= 3:
            return PlanVerdict(
                field_errors=dict(result.field_errors),
                failure_detail=_UNKNOWN_NOTE,
            )
        if result.field_errors:
            return PlanVerdict(field_errors=dict(result.field_errors))
    return PlanVerdict()


def build_probe(values: ConfigValues) -> ConnectionPlan:
    """造一份 AI 接口探测计划

    - 一行一通道，预算 20 秒
    - 请求值与免测键都取表单里那三项
    """
    base_url = _text(values, PluginKeys.BASE_URL)
    api_key = _text(values, PluginKeys.API_KEY)
    model = _text(values, PluginKeys.MODEL)
    return ConnectionPlan(
        rows=(ProbeRow(row_id=_ROW_ID, title=_ROW_TITLE),),
        channels=(
            ProbeChannel(
                row_id=_ROW_ID,
                label=_ROW_TITLE,
                budget=_BUDGET,
                run=lambda: _run(base_url, api_key, model),
            ),
        ),
        reuse_key=(base_url, api_key, model),
        finish=_finish,
    )
