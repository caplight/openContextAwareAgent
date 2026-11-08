"""上下文压缩测试（spec 补充：历史超限时的摘要 buffer）。"""

from __future__ import annotations

import asyncio

import pytest

from enterprise_kb import context as ctx


def test_estimate_tokens():
    assert ctx.estimate_tokens("中文测试") == 4  # 4 个中文字符
    assert ctx.estimate_tokens("hello world") == 2  # 11 英文 → 11//4 = 2
    assert ctx.estimate_tokens("") == 0


def test_compress_history_under_limit():
    history = [("user", "hi"), ("assistant", "hello")]
    out = asyncio.run(ctx.compress_history(history))
    assert out == history  # 未超限，原样返回


def test_compress_history_over_limit(monkeypatch):
    # 构造超限历史：中文长文本，确保超 8k token
    long_text = "中文" * 5000  # 10000 字符 ≈ 10000 token
    history = [("user", long_text), ("assistant", "ok")] * 5  # 10 条

    async def fake_summarize(msgs):
        return "这是摘要"

    monkeypatch.setattr(ctx, "_summarize", fake_summarize)

    out = asyncio.run(ctx.compress_history(history))
    # system 摘要 + 保留最近 KEEP_TURNS*2 = 6 条原文
    assert out[0] == ("system", "这是摘要")
    assert len(out) == 1 + 6
    # 保留的是最后 6 条
    assert out[1:] == history[-6:]


def test_compress_history_too_few_messages(monkeypatch):
    # 消息条数 <= 2（少于一轮）时不压缩（即便单条超长）
    long_text = "中文" * 5000
    history = [("user", long_text), ("assistant", long_text)]  # 2 条

    called = {"n": 0}

    async def fake_summarize(msgs):
        called["n"] += 1
        return "摘要"

    monkeypatch.setattr(ctx, "_summarize", fake_summarize)

    out = asyncio.run(ctx.compress_history(history))
    assert out == history  # 不压缩
    assert called["n"] == 0


def test_compress_history_few_but_long(monkeypatch):
    """条数少但单条超长时也应压缩（至少压掉最早一轮）。"""
    long_text = "中文" * 5000
    history = [("user", long_text), ("assistant", long_text)] * 3  # 6 条，超限

    async def fake_summarize(msgs):
        return "摘要"

    monkeypatch.setattr(ctx, "_summarize", fake_summarize)

    out = asyncio.run(ctx.compress_history(history))
    assert out[0] == ("system", "摘要")
    assert len(out) == 1 + 4  # system + 最近 2 轮（4 条）
