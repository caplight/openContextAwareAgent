"""FastAPI 层：SSE 流式聊天 + 会话管理 REST API（spec 第 5 节）。

- POST /api/chat             流式聊天（SSE），事件协议见 spec 5.1
- GET/POST /api/sessions     会话列表 / 新建
- GET/PATCH/DELETE /api/sessions/{id}   获取 / 重命名 / 删除
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from enterprise_kb import storage
from enterprise_kb.agent import astream
from enterprise_kb.config import get_settings

app = FastAPI(title="Kubernetes DevOps Assistant", version="0.1.0")


# ---------- 请求模型 ----------

class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class SessionCreate(BaseModel):
    title: str = ""


class SessionRename(BaseModel):
    title: str


# ---------- SSE 辅助 ----------

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


# 运行中的流式任务取消信号（run_id -> asyncio.Event）
_cancel_events: dict[str, asyncio.Event] = {}


# ---------- 会话管理 ----------

@app.get("/api/sessions")
def list_sessions():
    return [s.__dict__ for s in storage.list_sessions()]


@app.post("/api/sessions")
def create_session(req: SessionCreate):
    s = storage.create_session(title=req.title)
    return s.__dict__


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    s = storage.get_session(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {**s.__dict__, "messages": [m.__dict__ for m in storage.get_messages(session_id)]}


@app.patch("/api/sessions/{session_id}")
def rename_session(session_id: str, req: SessionRename):
    if not storage.rename_session(session_id, req.title):
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True}


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    if not storage.delete_session(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True}


# ---------- 流式聊天 ----------

@app.post("/api/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or storage.create_session().id
    storage.add_message(session_id, "user", req.message)
    model = get_settings().llm.primary
    run_id = str(uuid.uuid4())
    cancel_event = asyncio.Event()
    _cancel_events[run_id] = cancel_event
    # 读会话历史（排除刚写入的当前问题），供 agent 记住上下文（多轮对话）
    history = [(m.role, m.content) for m in storage.get_messages(session_id)[:-1]]

    async def event_stream() -> AsyncIterator[str]:
        answer_parts: list[str] = []
        tool_trace: list[storage.ToolCall] = []
        tool_meta: dict[str, dict] = {}  # run_id -> {name, args, start}

        yield _sse({"type": "meta", "session_id": session_id, "model": model, "run_id": run_id})

        try:
            async for e in astream(req.message, history=history):
                if cancel_event.is_set():
                    yield _sse({"type": "error", "message": "cancelled"})
                    return
                yield _sse(e)
                t = e["type"]
                if t == "text_delta":
                    answer_parts.append(e["delta"])
                elif t == "tool_start":
                    tool_meta[e["id"]] = {"name": e["name"], "args": e["args"], "start": time.time()}
                elif t == "tool_end":
                    meta = tool_meta.pop(e["id"], {})
                    duration = int((time.time() - meta.get("start", time.time())) * 1000)
                    tool_trace.append(
                        storage.ToolCall(
                            name=e["name"],
                            args=meta.get("args", {}),
                            output=e["output"],
                            status=e["status"],
                            duration_ms=duration,
                        )
                    )
                elif t == "done":
                    storage.add_message(session_id, "assistant", "".join(answer_parts), tool_trace)
        finally:
            _cancel_events.pop(run_id, None)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/chat/{run_id}/cancel")
async def cancel_chat(run_id: str):
    """中断某次流式运行（spec 5.3 / F6）。"""
    ev = _cancel_events.get(run_id)
    if ev:
        ev.set()
    return {"ok": True}


# ---------- 前端静态托管（生产单端口部署，spec 第 3 节）----------

WEB_DIST = Path(__file__).resolve().parent.parent.parent / "web" / "dist"

if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """SPA fallback：非 /api 路径返回 index.html（前端路由）。"""
        root = WEB_DIST.resolve()
        candidate = (root / full_path).resolve() if full_path else None
        # 静态文件（favicon 等）直接返回；否则 fallback 到 index.html
        if candidate and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        index = root / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="前端未构建（web/dist 缺失）")
