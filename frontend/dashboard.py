"""Streamlit 可观测 Dashboard：展示 Langfuse 里的 trace 指标。

三大观测点（对应 KPI #3）：
1. 延迟 —— 检索链路三段（retrieve / rerank / generate）各自耗时
2. token —— 每次生成的 input/output token 用量
3. 成本 —— 累计成本（generate span 的 cost_details）

数据源：自托管 Langfuse（REST API），每次点「刷新」拉最新 trace。
支持中英双语切换（sidebar 顶部）。
"""

import streamlit as st

from enterprise_kb.observability import fetch_recent_metrics
from locales import lang_selector, make_t

st.set_page_config(page_title="RAG 可观测 Dashboard", page_icon="📊", layout="wide")

lang = lang_selector()
t = make_t(lang)

st.title(t("dash_title"))
st.caption(t("dash_caption"))

st.sidebar.header(t("dash_sidebar_header"))
limit = st.sidebar.slider(t("dash_limit_slider"), 5, 100, 50, step=5)
if st.sidebar.button(t("dash_refresh"), use_container_width=True):
    st.rerun()

with st.spinner(t("dash_fetching")):
    metrics = fetch_recent_metrics(limit=limit)

if not metrics:
    st.info(t("dash_no_data"))
    st.stop()

total = len(metrics)

# ---------- 1. 汇总指标 ----------
c1, c2, c3, c4, c5 = st.columns(5)
avg_latency = sum(m["total_latency"] for m in metrics) / total
inp_tokens = sum(m["spans"].get("generate", {}).get("usage", {}).get("input", 0) for m in metrics)
out_tokens = sum(m["spans"].get("generate", {}).get("usage", {}).get("output", 0) for m in metrics)
total_cost = sum(m["total_cost"] for m in metrics)

c1.metric(t("metric_total_queries"), total)
c2.metric(t("metric_avg_latency"), f"{avg_latency:.2f}s")
c3.metric(t("metric_input_tokens"), f"{inp_tokens:,}")
c4.metric(t("metric_output_tokens"), f"{out_tokens:,}")
c5.metric(t("metric_total_cost"), f"${total_cost:.6f}")

st.divider()

# ---------- 2. 延迟分解表 ----------
st.subheader(t("latency_breakdown"))
rows = []
for m in metrics:
    spans = m["spans"]
    rows.append(
        {
            t("col_query"): (m["query"] or "")[:40],
            t("col_total_latency"): round(m["total_latency"], 3),
            t("col_retrieve"): round(spans.get("retrieve", {}).get("latency", 0), 3),
            t("col_rerank"): round(spans.get("rerank", {}).get("latency", 0), 3),
            t("col_generate"): round(spans.get("generate", {}).get("latency", 0), 3),
            t("col_model"): spans.get("generate", {}).get("model", ""),
            t("col_tokens"): spans.get("generate", {}).get("usage", {}).get("total", 0),
        }
    )

try:
    import pandas as pd

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, height=420)

    st.subheader(t("avg_latency_chart"))
    avg_retrieve = sum(m["spans"].get("retrieve", {}).get("latency", 0) for m in metrics) / total
    avg_rerank = sum(m["spans"].get("rerank", {}).get("latency", 0) for m in metrics) / total
    avg_generate = sum(m["spans"].get("generate", {}).get("latency", 0) for m in metrics) / total
    chart = pd.DataFrame(
        {
            t("col_stage"): ["retrieve", "rerank", "generate"],
            t("col_avg_latency"): [round(avg_retrieve, 3), round(avg_rerank, 3), round(avg_generate, 3)],
        }
    )
    st.bar_chart(chart.set_index(t("col_stage")))
except ImportError:
    st.warning("pandas not installed, skipping table/chart")
    for r in rows:
        st.write(r)

st.divider()

# ---------- 3. 查询历史 ----------
st.subheader(t("recent_queries"))
for m in list(reversed(metrics))[:10]:
    label = (m["query"] or t("no_query"))[:60]
    with st.expander(f"Q: {label}  ·  {m['total_latency']:.2f}s"):
        st.markdown(f"**{t('answer_prefix')}** {(m['answer'] or '')[:500]}")
        g = m["spans"].get("generate", {})
        st.caption(
            f"{t('col_model')} {g.get('model', '?')} · "
            f"{t('col_tokens')} {g.get('usage', {}).get('total', 0)} · "
            f"retrieve {m['spans'].get('retrieve', {}).get('latency', 0):.2f}s / "
            f"rerank {m['spans'].get('rerank', {}).get('latency', 0):.2f}s / "
            f"generate {g.get('latency', 0):.2f}s"
        )
