"""框架无关的联网搜索核心逻辑。

当本地知识库（kb_search）覆盖不足时，用 Brave Search API 联网补充信息。
薄封装：拼 HTTP 请求 → 返回格式化的搜索结果文本（标题+链接+摘要），
不做答案生成（与 kb_search 的「检索与生成分离」原则一致）。
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request

from enterprise_kb.core.result import SearchHit, SearchResult

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_MAX_DESC_CHARS = 400


def _get_brave_key() -> str | None:
    """从配置读取 Brave API key（SecretStr → 明文）。"""
    from enterprise_kb.config import get_settings

    settings = get_settings()
    if settings.brave_api_key:
        return settings.brave_api_key.get_secret_value()
    return None


def _strip_html(text: str) -> str:
    """去掉 HTML 标签（Brave 返回的描述里可能带 <strong> 等）。"""
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def web_search(query: str, top_k: int = 5) -> SearchResult:
    """联网搜索（Brave Search API），补充本地知识库未覆盖的信息。

    当 kb_search 检索不到相关内容时（如「CrashLoopBackOff 怎么排查」这类
    本地语料没有的知识），用这个工具联网搜索官方文档 / 社区答案。
    返回结构化 SearchResult（标题 + 链接 + 摘要），供后续综合判断；不生成最终答案。

    Args:
        query: 搜索查询（自然语言问题或关键词）
        top_k: 返回结果数，默认 5
    """
    key = _get_brave_key()
    if not key:
        return SearchResult(query=query, note="[错误] 未配置 BRAVE_API_KEY，无法联网搜索。")

    params = urllib.parse.urlencode({"q": query, "count": max(1, min(top_k, 20))})
    req = urllib.request.Request(
        f"{_BRAVE_SEARCH_URL}?{params}",
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return SearchResult(query=query, note=f"[错误] 联网搜索失败：{e}")

    results = (data.get("web") or {}).get("results", [])
    if not results:
        return SearchResult(query=query, note="[提示] 没有搜到相关结果。")

    hits = []
    for r in results[:top_k]:
        title = _strip_html(r.get("title") or "")
        url = r.get("url") or ""
        desc = _strip_html(r.get("description") or "")
        if len(desc) > _MAX_DESC_CHARS:
            desc = desc[: _MAX_DESC_CHARS] + "..."
        hits.append(SearchHit(title=title, url=url, snippet=desc))

    return SearchResult(query=query, hits=hits)
