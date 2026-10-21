"""UI 文案翻译字典（中英双语）。

Streamlit 无内置 i18n，这里用「翻译字典 + session_state 语言切换」自建。
所有前端文案从 `t(key)` 取值，切换语言后 rerun 生效。
"""

from __future__ import annotations

TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh": {
        # 语言切换器
        "lang_label": "语言 / Language",
        # ===== dashboard =====
        "dash_title": "📊 RAG 可观测 Dashboard",
        "dash_caption": "数据源：自托管 Langfuse（trace / span / token / 延迟）",
        "dash_sidebar_header": "⚙️ 控制",
        "dash_limit_slider": "拉取最近 N 条 trace",
        "dash_refresh": "🔄 刷新数据",
        "dash_fetching": "拉取 Langfuse trace…",
        "dash_no_data": "暂无 trace 数据。先跑几个查询（`POST /query` 或 Q&A 界面），再回来点「刷新」。",
        # 汇总指标
        "metric_total_queries": "总查询数",
        "metric_avg_latency": "平均总延迟",
        "metric_input_tokens": "总 input tokens",
        "metric_output_tokens": "总 output tokens",
        "metric_total_cost": "累计成本",
        # 延迟分解表
        "latency_breakdown": "⏱️ 检索链路延迟分解",
        "col_query": "query",
        "col_total_latency": "总延迟(s)",
        "col_retrieve": "retrieve(s)",
        "col_rerank": "rerank(s)",
        "col_generate": "generate(s)",
        "col_model": "模型",
        "col_tokens": "tokens",
        # 平均延迟图
        "avg_latency_chart": "📈 各环节平均延迟",
        "col_stage": "环节",
        "col_avg_latency": "平均延迟(s)",
        # 查询历史
        "recent_queries": "💬 最近查询",
        "no_query": "(无 query)",
        "answer_prefix": "A:",
        # ===== streamlit_app =====
        "app_title": "📚 企业知识库智能助手",
        "app_caption": "企业知识库 RAG 问答（hybrid 召回 + rerank 精排 + LLM 生成）",
        "app_input_label": "输入你的问题",
        "app_input_placeholder": "e.g. How do I scale a Kubernetes deployment?",
        "app_ask": "提问",
        "app_spinner": "检索 + 生成中…",
        "app_model_label": "模型",
        "app_contexts_label": "引用上下文",
        "app_segments_label": "段",
    },
    "en": {
        # 语言切换器
        "lang_label": "Language / 语言",
        # ===== dashboard =====
        "dash_title": "📊 RAG Observability Dashboard",
        "dash_caption": "Data source: self-hosted Langfuse (trace / span / token / latency)",
        "dash_sidebar_header": "⚙️ Controls",
        "dash_limit_slider": "Fetch last N traces",
        "dash_refresh": "🔄 Refresh",
        "dash_fetching": "Fetching Langfuse traces…",
        "dash_no_data": "No trace data yet. Run a few queries (`POST /query` or the Q&A page), then hit Refresh.",
        # 汇总指标
        "metric_total_queries": "Total Queries",
        "metric_avg_latency": "Avg Total Latency",
        "metric_input_tokens": "Total Input Tokens",
        "metric_output_tokens": "Total Output Tokens",
        "metric_total_cost": "Total Cost",
        # 延迟分解表
        "latency_breakdown": "⏱️ Retrieval Latency Breakdown",
        "col_query": "query",
        "col_total_latency": "total(s)",
        "col_retrieve": "retrieve(s)",
        "col_rerank": "rerank(s)",
        "col_generate": "generate(s)",
        "col_model": "Model",
        "col_tokens": "tokens",
        # 平均延迟图
        "avg_latency_chart": "📈 Avg Latency by Stage",
        "col_stage": "Stage",
        "col_avg_latency": "Avg Latency(s)",
        # 查询历史
        "recent_queries": "💬 Recent Queries",
        "no_query": "(no query)",
        "answer_prefix": "A:",
        # ===== streamlit_app =====
        "app_title": "📚 Enterprise KB Assistant",
        "app_caption": "Enterprise KB RAG Q&A (hybrid recall + rerank + LLM generation)",
        "app_input_label": "Ask a question",
        "app_input_placeholder": "e.g. How do I scale a Kubernetes deployment?",
        "app_ask": "Ask",
        "app_spinner": "Retrieving + generating…",
        "app_model_label": "Model",
        "app_contexts_label": "Referenced contexts",
        "app_segments_label": "segments",
    },
}


def lang_selector() -> str:
    """sidebar 语言切换器，返回当前语言代码（zh/en）。

    把语言存进 st.session_state，切换后 rerun 生效。
    """
    import streamlit as st

    if "lang" not in st.session_state:
        st.session_state.lang = "zh"

    current = st.session_state.lang
    selected = st.sidebar.selectbox(
        TRANSLATIONS[current]["lang_label"],
        ["zh", "en"],
        index=0 if current == "zh" else 1,
        format_func=lambda x: "中文" if x == "zh" else "English",
    )
    if selected != current:
        st.session_state.lang = selected
        st.rerun()
    return selected


def make_t(lang: str):
    """返回当前语言的翻译函数 t(key) -> str。"""

    def t(key: str) -> str:
        return TRANSLATIONS[lang].get(key, key)

    return t
