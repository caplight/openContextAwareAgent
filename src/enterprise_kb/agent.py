"""DevOps 助手 ReAct agent（Phase 3）。

用 LangGraph 的 create_react_agent 组装：一个 LLM（ChatLiteLLM）+ 工具池
（查集群 k8s_* + 查文档 kb_search）。agent 自主决定「这个问题该查集群还是查文档、
按什么顺序取证」，代码里不写死 if-else。

设计要点：
    - 被动响应：用户提问 → agent 多步取证 → 给结论，不主动做变更操作。
    - 方案 A：kb_search 只返回片段，agent 自己综合（检索与生成分离）。
    - 复用现有 llm 的 key 注入（_setup_keys）+ 配置（llm.primary）。
"""

from __future__ import annotations

from langchain_community.chat_models import ChatLiteLLM
from langgraph.prebuilt import create_react_agent

from enterprise_kb.config import get_settings
from enterprise_kb.llm import _setup_keys
from enterprise_kb.logging import get_logger
from enterprise_kb.tools import ALL_TOOLS

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "你是一名 Kubernetes DevOps 助手，帮助用户诊断和理解集群/工作负载的状态。\n"
    "你有两类工具：查集群（k8s_get / k8s_describe / k8s_logs / k8s_events）和 "
    "查文档（kb_search）。\n\n"
    "行为准则：\n"
    "1. 先取证再下结论：不要凭空猜测，用工具查清事实（状态 → 事件 → 日志），"
    "再做 root cause 分析。\n"
    "2. 根据问题类型选对工具：查「现在什么状态」用 k8s_get；查「为什么」用 "
    "k8s_describe + k8s_logs；查「时间线」用 k8s_events；查「最佳实践/怎么做」用 kb_search。\n"
    "3. 诚实：证据不足或查不到时，明确说「不确定」，不要编造。\n"
    "4. 只读不改：你不执行任何变更操作（不重启、不删除、不改配置），只做查看、分析、解释。\n"
    "5. 用简洁的中文回答，先给结论，再给依据。"
)


def build_agent():
    """构造 ReAct agent（LLM + 工具池）。"""
    _setup_keys()
    settings = get_settings()
    model = ChatLiteLLM(model=settings.llm.primary, temperature=settings.llm.temperature)
    logger.info("构建 DevOps ReAct agent，model=%s，tools=%d", settings.llm.primary, len(ALL_TOOLS))
    return create_react_agent(model, ALL_TOOLS, prompt=_SYSTEM_PROMPT)


# 模块级单例（供 API / CLI 复用）
agent = build_agent()


def ask(question: str) -> dict:
    """对外统一入口：输入问题，返回最终回答 + 完整消息轨迹。

    返回 dict：
        answer: 最终回答文本
        messages: 完整对话轨迹（含中间 tool 调用，供调试/可观测）
    """
    result = agent.invoke({"messages": [("user", question)]})
    messages = result.get("messages", [])
    answer = messages[-1].content if messages else ""
    return {"answer": answer, "messages": messages}
