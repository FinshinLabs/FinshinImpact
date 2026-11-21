"""对话工作循环

- 流式接收、会话落库与记录持久化
- 上下文超线从最旧一组问答丢起，丢空仍超即回一句不调模型
"""

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any, Literal

from finshin_sdk import HandlerContext
from finshin_sdk.domain.ids import SessionKey
from finshin_sdk.dto import InboundEventDTO
from finshin_sdk.exceptions import DomainError, MessageVanishedError
from utils import get_logger

from ..._shared.messages import BotMessage
from ..config import ai_config
from ..core import AIClient, StreamUsage, purge_stale, save_session
from ..markdown import strip_model_marks
from ..utils import (
    build_turns,
    compose_user_text,
    fit_history,
    learn_turn_overhead,
    make_rows,
    make_session_key,
    open_window,
)

_logger = get_logger("Plg.AI.Worker")


def _save_conversation_record(
    key: SessionKey, event: InboundEventDTO, final_msg: str
) -> None:
    """写入对话记录

    - 一群一份、一私聊一份，条目内注明发言人
    - 问句一行与交模型的 user 轮同文，网址留原文
    - 落盘失败只记错误，不影响本轮应答
    """
    wrt = (
        f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}\n\n"
        f"{compose_user_text(event)}\n\n"
        f"AI回复：\n{final_msg}\n\n\n"
    )
    try:
        with open(ai_config.record_dir / f"{key}.md", "a", encoding="utf8") as f:
            f.write(wrt)
    except Exception as e:
        _logger.send_error("保存本地对话记录失败", e)


async def _handle_ai_message(
    msg: list[dict[str, str]], usage: StreamUsage
) -> AsyncGenerator[tuple[Literal["final", "error"], Any], None]:
    """处理 AI 流式数据

    - 产出 (事件类型, 数据)
    """
    current_msg = ""

    try:
        async for delta in AIClient.stream_chat(msg, usage):
            if (content := delta.get("content")) is not None:
                if content.startswith("\n\n"):
                    content = content[2:]
                current_msg += content
        yield "final", current_msg
    except Exception as e:
        yield "error", e


async def _collect_reply(
    turns: list[dict[str, str]], key: SessionKey, tokens: int
) -> tuple[str, bool]:
    """收全一轮应答

    - 交出正文与是否出错
    - 拿到端点读数即倒推每条消息的打包开销并记一行
    """
    final_msg = ""
    has_error = False
    usage = StreamUsage()
    async for event_type, data in _handle_ai_message(turns, usage):
        match event_type:
            case "final":
                final_msg = data
            case "error":
                _logger.send_error("流式处理错误", data)
                has_error = True
    if usage.prompt_tokens is not None:
        learn_turn_overhead(turns, usage.prompt_tokens)
        _logger.debug(
            f"{key} 上下文估算 {tokens}，{len(turns)} 条，端点报 {usage.prompt_tokens}"
        )
    return final_msg, has_error


async def worker_loop(ctx: HandlerContext) -> None:
    """核心工作循环"""
    text = ctx.event.content.text
    if not text:
        _logger.debug("消息无文本，跳过")
        return

    # 任务开始前探一次，原消息已删即中断，不持续轮询
    if not await ctx.interaction.probe_existence(ctx.event.ref):
        raise MessageVanishedError(ctx.event.ref)

    session_key = make_session_key(ctx.event.principal)

    # 人设轮每轮按当前配置与磁盘正文重取，库里那行人设正文只当版本标记
    persona = ai_config.init[0]["content"]

    # 库里的人设版本对不上即换过人设或主人，所有人的记录连带库一起清
    snapshot = await purge_stale(persona, session_key)

    window = open_window(persona, snapshot.messages)
    prompt = compose_user_text(ctx.event)

    # 超线从最旧一组问答丢起，丢空仍超即不再调模型，本轮不入库不落记录
    limit = ai_config.context_tokens
    history, tokens = fit_history(persona, window[1:], prompt, limit)
    if tokens > limit:
        await ctx.reply(BotMessage.AI_CONTEXT_OVERFLOW)
        return
    window = (window[0], *history)

    msg = build_turns(persona=persona, history=history, thisinput=prompt)

    try:
        final_msg, has_error = await _collect_reply(msg, session_key, tokens)
        if has_error or not final_msg:
            await ctx.reply(BotMessage.AI_UNAVAILABLE)
            return

        # 漏网样式在入库前洗掉，发出、落记录与回喂模型的三路拿到的都是纯文本
        final_msg = strip_model_marks(final_msg)

        # 分段与防频控归适配层端口，此处只交整段正文
        await ctx.reply(final_msg)

        await save_session(session_key, (*window, *make_rows(ctx.event, final_msg)))

        await asyncio.to_thread(
            _save_conversation_record, session_key, ctx.event, final_msg
        )

    except DomainError:
        raise
    except Exception as e:
        _logger.send_error("Worker 运行时错误", e)
        await ctx.reply(BotMessage.AI_UNAVAILABLE)
