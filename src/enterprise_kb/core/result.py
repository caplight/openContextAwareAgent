"""检索结果的结构化数据模型（供引用来源展示 + LLM 文本）。

单一真相源：core 层工具返回结构化 `SearchResult`；给 LLM 的纯文本（`to_text`）
和给前端的引用来源（`to_sources`）都是它的派生视图。这样 agent 逻辑不变，
前端又能拿到可点击的引用（spec F9 / 方案 B）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SearchHit:
    """一条检索结果。

    - kb_search：只有 `snippet`（文档片段），`title`/`url` 为空。
    - web_search：`title` + `url` + `snippet`（摘要）齐全。
    """

    snippet: str = ""
    title: str | None = None
    url: str | None = None

    def to_text(self) -> str:
        """给 LLM 看的单条文本。web 结果带标题+链接，kb 结果只有片段。"""
        if self.title and self.url:
            return f"{self.title}\n    {self.url}\n    {self.snippet}"
        return self.snippet


@dataclass
class SearchResult:
    """一次检索的完整结构化结果。"""

    query: str
    hits: list[SearchHit] = field(default_factory=list)
    note: str = ""  # hits 为空时的提示（空结果/错误信息，由具体工具填写）

    def to_text(self) -> str:
        """给 LLM 的纯文本（带编号，供 agent 综合判断）。"""
        if not self.hits:
            return self.note or "(无结果)"
        return "\n\n".join(f"[{i + 1}] {h.to_text()}" for i, h in enumerate(self.hits))

    def to_sources(self) -> list[dict]:
        """给前端的结构化引用来源（可点击）。"""
        return [
            {
                "title": h.title or (h.snippet[:50] + "…" if len(h.snippet) > 50 else h.snippet),
                "url": h.url,
                "snippet": h.snippet[:300],
            }
            for h in self.hits
        ]
