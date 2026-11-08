"""Spike：验证 create_react_agent 的 astream_events 事件流。

目的（对应 spec Q5）：
1. 能否拿到 token 流（on_chat_model_stream）
2. 能否拿到 tool_start / tool_end
3. deepseek 的 reasoning_content 是否在流式 chunk 里（决定 F3 可行性）
"""
from __future__ import annotations

import asyncio
import json

from enterprise_kb.agent import agent


async def main() -> None:
    print("=== astream_events spike ===")
    kinds: dict[str, int] = {}
    sample_reasoning = ""
    tool_names: list[str] = []
    first_token = ""

    async for event in agent.astream_events(
        {"messages": [("user", "我的集群有哪些节点？")]},
        version="v2",
    ):
        kind = event["event"]
        kinds[kind] = kinds.get(kind, 0) + 1

        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            content = getattr(chunk, "content", "") or ""
            if content and not first_token:
                first_token = content
            # deepseek 思考内容在 additional_kwargs 或 reasoning_content
            ak = getattr(chunk, "additional_kwargs", {}) or {}
            rc = ak.get("reasoning_content", "") or ak.get("reasoning", "")
            if rc:
                sample_reasoning += rc

        elif kind == "on_tool_start":
            tool_names.append(event["name"])

    print("事件类型计数:", json.dumps(kinds, ensure_ascii=False))
    print("工具调用序列:", tool_names)
    print("首 token:", repr(first_token[:50]))
    print("reasoning_content 样本:", repr(sample_reasoning[:200]) or "(空 — 流式拿不到思考内容)")


asyncio.run(main())
