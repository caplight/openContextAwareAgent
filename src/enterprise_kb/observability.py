"""观测数据获取：从自托管 Langfuse 拉 trace 数据（供 Streamlit dashboard 消费）。

数据流：Langfuse REST API（basic auth = PK:SK）→ 结构化指标 dict。
dashboard 只依赖本模块，不直接碰 HTTP / 解析细节。
"""

from __future__ import annotations

import requests

from enterprise_kb.config import get_settings
from enterprise_kb.logging import get_logger

logger = get_logger(__name__)


def _client() -> tuple[str, tuple[str, str]]:
    """返回 (host, (public_key, secret_key)) 供 requests 使用。"""
    settings = get_settings()
    return settings.langfuse.host.rstrip("/"), (
        settings.langfuse.public_key,
        settings.langfuse.secret_key,
    )


def list_traces(limit: int = 50) -> list[dict]:
    """拉最近 N 条 trace（按时间倒序）。"""
    host, auth = _client()
    try:
        r = requests.get(
            f"{host}/api/public/traces",
            params={"limit": limit, "orderBy": "timestamp.desc"},
            auth=auth,
            timeout=15,
            proxies={"http": None, "https": None},
        )
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as e:  # noqa: BLE001
        logger.warning("拉取 trace 列表失败: %s", e)
        return []


def trace_detail(trace_id: str) -> dict | None:
    """拉单条 trace 详情（observations 已内联）。"""
    host, auth = _client()
    try:
        r = requests.get(
            f"{host}/api/public/traces/{trace_id}",
            auth=auth,
            timeout=15,
            proxies={"http": None, "https": None},
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("拉取 trace 详情失败 %s: %s", trace_id, e)
        return None


def parse_trace_metrics(detail: dict) -> dict:
    """从 trace 详情提取观测指标。

    返回：
        {
          "trace_id": ...,
          "name": ...,
          "query": ...,
          "answer": ...,
          "total_latency": ...,
          "total_cost": ...,
          "spans": {
             "retrieve": {"latency": ..., "usage": {...}},
             "rerank":   {"latency": ..., "usage": {...}},
             "generate": {"latency": ..., "usage": {...}, "model": ...},
          }
        }
    """
    spans: dict[str, dict] = {}
    for o in detail.get("observations", []):
        name = o.get("name")
        if not name:
            continue
        spans[name] = {
            "type": o.get("type"),
            "latency": o.get("latency") or 0.0,
            "usage": o.get("usageDetails") or {},
            "model": o.get("model"),
        }

    inp = detail.get("input") or {}
    out = detail.get("output") or {}
    return {
        "trace_id": detail.get("id"),
        "name": detail.get("name"),
        "timestamp": detail.get("timestamp"),
        "query": inp.get("query", "") if isinstance(inp, dict) else "",
        "answer": out.get("answer", "") if isinstance(out, dict) else "",
        "model": out.get("model", "") if isinstance(out, dict) else "",
        "total_latency": detail.get("latency") or 0.0,
        "total_cost": detail.get("totalCost") or 0.0,
        "spans": spans,
    }


def fetch_recent_metrics(limit: int = 50) -> list[dict]:
    """拉最近 N 条 rag-query trace 的完整指标（列表 + 逐条详情）。

    只返回 name == 'rag-query' 的 trace（过滤掉 smoke test 等杂项）。
    """
    traces = list_traces(limit=limit)
    metrics: list[dict] = []
    for t in traces:
        if t.get("name") != "rag-query":
            continue
        detail = trace_detail(t["id"])
        if detail:
            metrics.append(parse_trace_metrics(detail))
    return metrics
