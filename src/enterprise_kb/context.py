"""上下文压缩（摘要 buffer，业界标准做法）。

历史消息超过 token 阈值时，用 LLM 把最老的消息压成一段摘要，保留最近 K 轮原文，
防止无限堆历史导致超出模型上下文窗口。

设计：
    - 触发：历史总 token > MAX_TOKENS
    - 策略：保留最近 KEEP_TURNS 轮原文，更早的压成摘要
    - 注入：摘要作为 system 消息放在 history 最前
    - 不持久化：每次请求读历史时动态计算（只在超限时多一次 LLM 调用）
"""

from __future__ import annotations

import re

from langchain_community.chat_models import ChatLiteLLM

from enterprise_kb.config import get_settings
from enterprise_kb.llm import _setup_keys

# 压缩阈值与保留轮数已在 config（Settings.context）中配置，
# 可用环境变量 CONTEXT__MAX_TOKENS / CONTEXT__KEEP_TURNS 覆盖。

_SUMMARY_PROMPT = (
    "你是对话摘要器。请把下面的对话压缩成一段简洁的摘要，保留对后续对话有帮助的关键信息：\n"
    "1. 用户的核心目标与约束\n"
    "2. 已确认的关键事实（尤其是技术结论，如环境、版本、根因、集群/节点状态）\n"
    "3. 进行中或未完成的任务\n"
    "4. 用户明确的偏好或待办\n\n"
    "要求：不要流水账复述，用简洁要点；摘要语言跟随对话语言（中文对话用中文，英文对话用英文）。\n\n"
    "对话：\n{conversation}\n\n"
    "摘要："
)


def estimate_tokens(text: str) -> int:
    """粗估 token 数：中文 1 字符≈1 token，其余 4 字符≈1 token。

    无需引入 tiktoken 依赖，误差对「是否触发压缩」的粗判断足够。
    """
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    return cjk + (len(text) - cjk) // 4


def _total_tokens(history: list[tuple[str, str]]) -> int:
    return sum(estimate_tokens(c) for _, c in history)


async def compress_history(history: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """历史超阈值时，把最老消息压成摘要，保留最近 keep_turns 轮原文。

    未超限、或消息条数少于一轮（2 条，无压缩空间）时原样返回。
    阈值与保留轮数由 config.context 控制。
    """
    settings = get_settings()
    if _total_tokens(history) <= settings.context.max_tokens:
        return history

    if len(history) <= 2:
        # 少于一轮（user+assistant），没有可压缩的空间（罕见：单轮超长）
        return history

    # 保留最近 keep_turns 轮，但至少压掉最早的 2 条（一轮），
    # 避免条数少但单条超长时「无法压缩」导致的超限。
    keep_count = min(settings.context.keep_turns * 2, len(history) - 2)
    keep = history[-keep_count:]
    to_compress = history[:-keep_count]

    summary = await _summarize(to_compress)
    return [("system", summary), *keep]


async def _summarize(msgs: list[tuple[str, str]]) -> str:
    """调用 LLM 把消息列表压成一段摘要。"""
    _setup_keys()
    settings = get_settings()
    model = ChatLiteLLM(model=settings.llm.primary, temperature=0.3)
    conv = "\n".join(f"{role}: {content}" for role, content in msgs)
    resp = await model.ainvoke(_SUMMARY_PROMPT.format(conversation=conv))
    return resp.content if hasattr(resp, "content") else str(resp)
