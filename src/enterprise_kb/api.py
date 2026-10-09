"""FastAPI 入口（M1.5）：/ingest（摄入建索引）+ /query（问答）。"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from enterprise_kb.embed import index_chunks
from enterprise_kb.graph import ask
from enterprise_kb.ingest import load_and_split
from enterprise_kb.tracing import trace_query

app = FastAPI(title="Enterprise Knowledge Base Assistant", version="0.1.0")


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    answer: str
    contexts: list[str]
    model: str


class IngestResponse(BaseModel):
    indexed_chunks: int


@app.post("/ingest", response_model=IngestResponse)
def ingest() -> IngestResponse:
    """摄入 data/docs 下所有文档并建索引。"""
    chunks = load_and_split()
    if not chunks:
        raise HTTPException(status_code=400, detail="data/docs 下没有可摄入的文档")
    n = index_chunks(chunks)
    return IngestResponse(indexed_chunks=n)


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    """问答：检索 + 生成。"""
    result = ask(req.query)
    trace_query(
        req.query,
        result["contexts"],
        result["answer"],
        model=result.get("model"),
    )
    return QueryResponse(
        answer=result["answer"],
        contexts=result["contexts"],
        model=result["model"],
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
