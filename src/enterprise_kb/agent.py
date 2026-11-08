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

import re
import time

from langchain_community.chat_models import ChatLiteLLM
from langgraph.prebuilt import create_react_agent

from enterprise_kb.config import get_settings
from enterprise_kb.llm import _setup_keys
from enterprise_kb.logging import get_logger
from enterprise_kb.tools import ALL_TOOLS

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "你是一名 Kubernetes DevOps 助手，帮助用户诊断和理解集群/工作负载的状态。\n"
    "你有三类工具：查集群（k8s_get / k8s_describe / k8s_logs / k8s_events）、"
    "查本地文档（kb_search）、联网搜索（web_search）。\n\n"
    "行为准则：\n"
    "1. 先取证再下结论：不要凭空猜测，用工具查清事实（状态 → 事件 → 日志），"
    "再做 root cause 分析。\n"
    "2. 根据问题类型选对工具：查「现在什么状态」用 k8s_get；查「为什么」用 "
    "k8s_describe + k8s_logs；查「时间线」用 k8s_events；查「最佳实践/怎么做」先试 "
    "kb_search（本地文档），本地检索不到相关内容或覆盖不足时，再用 web_search 联网补充"
    "（官方文档 / 社区答案）。\n"
    "3. 诚实：证据不足或查不到时，明确说「不确定」，不要编造；联网搜索结果要标注来源链接。\n"
    "4. 只读不改：你不执行任何变更操作（不重启、不删除、不改配置），只做查看、分析、解释。\n"
    "5. 用与用户提问相同的语言回答（用户用英文问就用英文答，用中文问就用中文答），先给结论，再给依据。\n"
    "6. 调用工具前不要输出任何开场白、进度说明或对用户的过渡话（如「我先查一下」），直接静默调用工具取证，全部取证完成后一次性给出完整结论。"
)


def build_agent(lang: str | None = None):
    """构造 ReAct agent（LLM + 工具池）。

    lang 为 None 时不追加语言约束；为 'zh'/'en' 时追加硬性语言要求，
    保证回复全程单一语言（防止 deepseek-flash 中英文混用）。
    """
    _setup_keys()
    settings = get_settings()
    model = ChatLiteLLM(model=settings.llm.primary, temperature=settings.llm.temperature)
    prompt = _SYSTEM_PROMPT
    if lang == "zh":
        prompt += (
            "\n\n【硬性语言要求】本次对话必须全程用中文回答，从第一个字到最后一个字都是中文，"
            "严禁中英文混用（专有名词、命令、代码、技术术语可保留英文原文）。"
        )
    elif lang == "en":
        prompt += (
            "\n\n【硬性语言要求】本次对话必须全程用英文回答，从第一个字到最后一个字都是英文，"
            "严禁中英文混用（专有名词、命令、代码、技术术语可保留原文）。"
        )
    logger.info("构建 DevOps ReAct agent，model=%s，tools=%d，lang=%s", settings.llm.primary, len(ALL_TOOLS), lang)
    return create_react_agent(model, ALL_TOOLS, prompt=prompt)


def _detect_lang(text: str) -> str:
    """检测文本语言：含中文字符 → 'zh'，否则 'en'。"""
    return "zh" if re.search(r"[\u4e00-\u9fff]", text) else "en"


# 按语言缓存的 agent 单例（zh / en 各一个，避免每次重建）
_agents: dict[str, object] = {}


def _get_agent(lang: str):
    if lang not in _agents:
        _agents[lang] = build_agent(lang)
    return _agents[lang]


# 模块级单例（供 API / CLI 复用，默认无语言约束）
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


async def astream(question: str):
    """流式版 ask：逐事件 yield dict，供 SSE 层转发（spec 第 5.1 节）。

    产出的事件类型：
        reasoning_start / reasoning_delta / reasoning_end  — agent 思考过程（F3）
        tool_start / tool_end                             — 工具调用（F2）
        text_delta                                        — 回答文本增量（F1）
        citations                                         — 结构化引用来源（F9）
        done / error                                      — 终止事件
    """
    in_reasoning = False
    reasoning_step = 0
    tool_start_ts: dict[str, float] = {}
    answer_parts: list[str] = []
    lang = _detect_lang(question)
    agent_for_lang = _get_agent(lang)
    try:
        async for event in agent_for_lang.astream_events(
            {"messages": [("user", question)]},
            version="v2",
        ):
            kind = event["event"]

            if kind == "on_chat_model_start":
                in_reasoning = False  # 新一轮 LLM 调用，重置思考状态

            elif kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                rc = (getattr(chunk, "additional_kwargs", {}) or {}).get("reasoning_content", "") or ""
                content = getattr(chunk, "content", "") or ""
                if rc and not in_reasoning:
                    in_reasoning = True
                    reasoning_step += 1
                    yield {"type": "reasoning_start", "step": reasoning_step}
                if rc:
                    yield {"type": "reasoning_delta", "delta": rc}
                if content and in_reasoning:
                    in_reasoning = False
                    yield {"type": "reasoning_end"}
                if content:
                    answer_parts.append(content)
                    yield {"type": "text_delta", "delta": content}

            elif kind == "on_tool_start":
                tool_start_ts[event["run_id"]] = time.time()
                yield {
                    "type": "tool_start",
                    "id": event["run_id"],
                    "name": event["name"],
                    "args": event["data"].get("input", {}),
                }

            elif kind == "on_tool_end":
                output = event["data"].get("output")
                content, artifact = _extract_tool_output(output)
                start = tool_start_ts.pop(event["run_id"], time.time())
                yield {
                    "type": "tool_end",
                    "id": event["run_id"],
                    "name": event["name"],
                    "output": content,
                    "status": "success",
                    "duration_ms": int((time.time() - start) * 1000),
                }
                if artifact:
                    yield {"type": "citations", "sources": artifact}

        yield {"type": "done", "answer": "".join(answer_parts)}
    except Exception as e:  # noqa: BLE001
        logger.exception("agent 流式执行失败")
        yield {"type": "error", "message": str(e)}


def _extract_tool_output(output) -> tuple[str, list | None]:
    """从 on_tool_end 的 output 提取（纯文本, 结构化引用）。

    content_and_artifact 工具的 output 是 ToolMessage（content + artifact）；
    普通工具是 ToolMessage（仅 content）或裸 str。防御性处理多种结构。
    """
    content = ""
    artifact = None
    if output is None:
        content = ""
    elif isinstance(output, str):
        content = output
    elif hasattr(output, "content"):
        content = output.content or ""
        artifact = getattr(output, "artifact", None)
        if not artifact:
            artifact = None
    else:
        content = str(output)
    # artifact 可能不是 list（异常结构），统一成 list 或 None
    if isinstance(artifact, list):
        return content, artifact
    return content, None
