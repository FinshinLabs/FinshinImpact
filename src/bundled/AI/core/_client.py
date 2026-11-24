"""AI 客户端

- 鉴权头注入与禁用代理
- 探测请求的状态码失败原样上抛，由探测层决定怎么展示
- 流式请求失败把状态码与正文写进日志
"""

import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from exceptions import HTTPStatusError
from system.atomic_write import write_text_atomic
from utils import get_logger
from utils.network import BaseClient
from utils.paths import PROFILE_DIR

from ..config import ai_config

_logger = get_logger("Plg.AI.Client")

# 接口不认推理强度开关时的状态码
_REASONING_REJECT = (400, 422)
_REASONING_FIELD = "reasoning_effort"

# 拒收组合记在实例目录，重启后仍照旧不带这个字段
_CACHE_FILE = PROFILE_DIR / "ai_no_reasoning.json"
_CACHE_KEY = "no_reasoning_effort"

# 首次用到时从缓存文件读出
_rejected_pairs: set[tuple[str, str]] | None = None


def _load_rejected() -> set[tuple[str, str]]:
    """从实例缓存读出拒收组合，读不出按空表算"""
    try:
        raw = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    entries = raw.get(_CACHE_KEY) if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return set()
    return {
        (str(item["base_url"]), str(item["model"]))
        for item in entries
        if isinstance(item, dict) and "base_url" in item and "model" in item
    }


def _rejected() -> set[tuple[str, str]]:
    """当前进程读到的拒收组合"""
    global _rejected_pairs
    if _rejected_pairs is None:
        _rejected_pairs = _load_rejected()
    return _rejected_pairs


def _remember_rejected(base_url: str | None = None, model: str | None = None) -> None:
    """去字段重发通过后写进实例缓存，下次不再带"""
    key = (
        base_url or ai_config.base_url,
        model or ai_config.model_name,
    )
    known = _rejected()
    if key in known:
        return
    known.add(key)
    entries = [
        {"base_url": base_url, "model": model} for base_url, model in sorted(known)
    ]
    try:
        write_text_atomic(
            _CACHE_FILE,
            json.dumps({_CACHE_KEY: entries}, ensure_ascii=False, indent=2),
        )
    except OSError as e:
        _logger.info(f"没把拒收组合写进实例缓存：{e}")
    _logger.info("该接口不认 reasoning_effort，后续请求不再发送")


@dataclass
class StreamUsage:
    """流式请求的 token 读数容器"""

    prompt_tokens: int | None = None


class AIClient(BaseClient):
    """鉴权与禁代理客户端"""

    @classmethod
    def _headers(cls, api_key: str | None = None) -> dict[str, str]:
        key = ai_config.api_key if api_key is None else api_key
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    @classmethod
    def _payload(
        cls,
        msg: list[dict[str, str]] | None,
        *,
        stream: bool,
        max_tokens: int | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """按点名值或当前配置拼请求体"""
        model_name = ai_config.model_name if model is None else model
        url = ai_config.base_url if base_url is None else base_url
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": msg,
            "stream": stream,
            "temperature": ai_config.temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if (url, model_name) not in _rejected():
            payload[_REASONING_FIELD] = "none"
        return payload

    @classmethod
    def _without_reasoning(
        cls,
        err: HTTPStatusError,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """摘掉推理强度开关交出重发用的请求体

        - 本来就没带这个字段，或状态码不是 400/422，原样抛出
        """
        if _REASONING_FIELD not in payload or err.status_code not in _REASONING_REJECT:
            raise err
        return {key: value for key, value in payload.items() if key != _REASONING_FIELD}

    @staticmethod
    def _log_stream_error(err: HTTPStatusError) -> None:
        """流式失败把状态码与正文写进日志"""
        _logger.error(f"流式请求失败：HTTP {err.status_code} {err.msg}")

    @classmethod
    async def stream_chat(
        cls,
        msg: list[dict[str, str]] | None = None,
        usage: StreamUsage | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """AI 流式聊天请求

        - 解析 SSE delta
        - 交入读数容器即写入端点报的输入 token 数
        """
        payload = cls._payload(msg, stream=True)
        try:
            async for delta in cls._stream_deltas(payload, usage):
                yield delta
        except HTTPStatusError as e:
            try:
                retry_payload = cls._without_reasoning(e, payload)
            except HTTPStatusError:
                cls._log_stream_error(e)
                raise
            try:
                async for delta in cls._stream_deltas(retry_payload, usage):
                    yield delta
            except HTTPStatusError as retry_error:
                cls._log_stream_error(retry_error)
                raise
            _remember_rejected()

    @classmethod
    async def _stream_deltas(
        cls,
        payload: dict[str, Any],
        usage: StreamUsage | None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """发一次流式请求并逐帧交 delta"""
        async for line in super().stream_post(
            base_url=ai_config.base_url,
            request_path=ai_config.request_path,
            headers=cls._headers(),
            payload=payload,
        ):
            if not line.startswith("data: "):
                continue
            try:
                data = json.loads(line[6:])

                # 末帧只带读数不带 choices，取完照旧走异常跳过
                if usage is not None and (read := data.get("usage")):
                    usage.prompt_tokens = read["prompt_tokens"]

                yield data["choices"][0]["delta"]
            except (json.JSONDecodeError, KeyError, IndexError):
                continue

    @classmethod
    async def list_models(cls, base_url: str, api_key: str) -> Any:
        """取站点的模型列表

        - 只用来确认地址和密钥是否已通，正文不解析
        """
        return await super().get_content(
            "json",
            base_url=base_url,
            request_path="/models",
            headers=cls._headers(api_key),
        )

    @classmethod
    async def probe(
        cls,
        msg: list[dict[str, str]],
        max_tokens: int,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> Any:
        """AI 非流式探测请求

        - 传入的地址、密钥与模型名优先于配置值，探测值不必先落盘
        - 状态码失败原样上抛，由探测层展示
        - 调试日志只落状态码、地址与模型名
        """
        url = ai_config.base_url if base_url is None else base_url
        model_name = ai_config.model_name if model is None else model
        try:
            return await cls._probe(
                msg, max_tokens, base_url=url, api_key=api_key, model=model_name
            )
        except HTTPStatusError as e:
            _logger.debug(f"接口返回 {e.status_code} 地址 {url} 模型 {model_name}")
            raise

    @classmethod
    async def _probe(
        cls,
        msg: list[dict[str, str]],
        max_tokens: int,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
    ) -> Any:
        """按定好的地址与模型名发一次探测请求

        - 接口不认推理强度开关时去掉该字段重发一次
        """
        payload = cls._payload(
            msg, stream=False, max_tokens=max_tokens, model=model, base_url=base_url
        )
        try:
            return await super().post_json(
                base_url=base_url,
                request_path=ai_config.request_path,
                headers=cls._headers(api_key),
                payload=payload,
            )
        except HTTPStatusError as e:
            retry_payload = cls._without_reasoning(e, payload)
            result = await super().post_json(
                base_url=base_url,
                request_path=ai_config.request_path,
                headers=cls._headers(api_key),
                payload=retry_payload,
            )
            _remember_rejected(base_url=base_url, model=model)
            return result
