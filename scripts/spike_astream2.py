"""Spike：验证 agent.astream 的事件流（reasoning / tool / text / citations）。"""
from __future__ import annotations

import asyncio

from enterprise_kb.agent import astream


async def run(question: str) -> None:
    print(f"\n{'='*60}\n问题: {question}\n{'='*60}")
    async for e in astream(question):
        t = e["type"]
        if t == "reasoning_start":
            print("\n[reasoning_start]")
        elif t == "reasoning_delta":
            print(e["delta"], end="", flush=True)
        elif t == "reasoning_end":
            print("\n[reasoning_end]")
        elif t == "tool_start":
            print(f"\n[tool_start] {e['name']}({e['args']})")
        elif t == "tool_end":
            print(f"[tool_end] {e['name']} output_len={len(e['output'])}")
        elif t == "text_delta":
            print(e["delta"], end="", flush=True)
        elif t == "citations":
            print(f"\n[citations] {len(e['sources'])} 条:")
            for s in e["sources"]:
                print(f"    - {s.get('title','')[:40]} | {s.get('url','')}")
        elif t == "done":
            print("\n[done]")
        elif t == "error":
            print(f"\n[error] {e['message']}")


async def main() -> None:
    await run("我的集群有哪些节点？")


asyncio.run(main())
