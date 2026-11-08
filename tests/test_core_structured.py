"""core 层结构化引用测试（F9 / spec 8）。

覆盖 SearchHit / SearchResult 的 to_text / to_sources 派生视图，
以及 tools._wrap_search 的 content_and_artifact 包装。
"""

from __future__ import annotations

from enterprise_kb.core.result import SearchHit, SearchResult
from enterprise_kb.tools import _wrap_search, kb_search, web_search


# ---------- SearchHit ----------


def test_hit_to_text_web():
    h = SearchHit(snippet="摘要", title="标题", url="https://x")
    assert h.to_text() == "标题\n    https://x\n    摘要"


def test_hit_to_text_kb_only_snippet():
    h = SearchHit(snippet="纯片段")
    assert h.to_text() == "纯片段"


# ---------- SearchResult.to_text ----------


def test_result_to_text_numbered():
    r = SearchResult(query="q", hits=[SearchHit(snippet="a"), SearchHit(snippet="b")])
    assert r.to_text() == "[1] a\n\n[2] b"


def test_result_to_text_empty_uses_note():
    r = SearchResult(query="q", note="无结果")
    assert r.to_text() == "无结果"


def test_result_to_text_empty_no_note():
    r = SearchResult(query="q")
    assert r.to_text() == "(无结果)"


# ---------- SearchResult.to_sources ----------


def test_result_to_sources_structure():
    r = SearchResult(
        query="q",
        hits=[SearchHit(snippet="s", title="t", url="https://u")],
    )
    src = r.to_sources()[0]
    assert src["title"] == "t"
    assert src["url"] == "https://u"
    assert src["snippet"] == "s"


def test_result_to_sources_kb_title_from_snippet():
    r = SearchResult(query="q", hits=[SearchHit(snippet="x" * 10)])
    src = r.to_sources()[0]
    assert src["title"] == "x" * 10  # 短 snippet 不截断
    assert src["url"] is None


def test_result_to_sources_snippet_truncated_to_300():
    long = "x" * 500
    r = SearchResult(query="q", hits=[SearchHit(snippet=long)])
    assert len(r.to_sources()[0]["snippet"]) == 300


# ---------- _wrap_search (content_and_artifact) ----------


def test_wrap_search_returns_content_and_artifact():
    def fake(query: str, top_k: int = 5) -> SearchResult:
        """fake search tool docstring."""
        return SearchResult(query=query, hits=[SearchHit(snippet="s", title="t", url="https://u")])

    tool = _wrap_search(fake)
    assert tool.name == "fake"
    assert tool.response_format == "content_and_artifact"

    # 底层 _runner 返回 (content, artifact) 元组；agent 层把它包成 ToolMessage
    content, artifact = tool.func("q", 5)
    assert content == "[1] t\n    https://u\n    s"  # to_text（带编号）
    assert artifact[0]["title"] == "t"  # to_sources
    assert artifact[0]["url"] == "https://u"


def test_search_tools_are_wrapped():
    # kb_search / web_search 都是 content_and_artifact 工具
    assert kb_search.response_format == "content_and_artifact"
    assert web_search.response_format == "content_and_artifact"
