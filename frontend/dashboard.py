"""Streamlit 可观测 Dashboard：展示 Langfuse 里的 trace 指标。

三大观测点（对应 KPI #3）：
1. 延迟 —— 检索链路三段（retrieve / rerank / generate）各自耗时
2. token —— 每次生成的 input/output token 用量
3. 成本 —— 累计成本（generate span 的 cost_details）

数据源：自托管 Langfuse（REST API），每次点「刷新」拉最新 trace。
"""

import streamlit as st

from enterprise_kb.observability import fetch_recent_metrics

st.set_page_config(page_title="RAG 可观测 Dashboard", page_icon="📊", layout="wide")
st.title("📊 RAG 可观测 Dashboard")
st.caption("数据源：自托管 Langfuse（trace / span / token / 延迟）")

st.sidebar.header("⚙️ 控制")
limit = st.sidebar.slider("拉取最近 N 条 trace", 5, 200, 50, step=5)
if st.sidebar.button("🔄 刷新数据", use_container_width=True):
    st.rerun()

with st.spinner("拉取 Langfuse trace…"):
    metrics = fetch_recent_metrics(limit=limit)

if not metrics:
    st.info("暂无 trace 数据。先跑几个查询（`POST /query` 或 Q&A 界面），再回来点「刷新」。")
    st.stop()

total = len(metrics)

# ---------- 1. 汇总指标 ----------
c1, c2, c3, c4, c5 = st.columns(5)
avg_latency = sum(m["total_latency"] for m in metrics) / total
inp_tokens = sum(m["spans"].get("generate", {}).get("usage", {}).get("input", 0) for m in metrics)
out_tokens = sum(m["spans"].get("generate", {}).get("usage", {}).get("output", 0) for m in metrics)
total_cost = sum(m["total_cost"] for m in metrics)

c1.metric("总查询数", total)
c2.metric("平均总延迟", f"{avg_latency:.2f}s")
c3.metric("总 input tokens", f"{inp_tokens:,}")
c4.metric("总 output tokens", f"{out_tokens:,}")
c5.metric("累计成本", f"${total_cost:.6f}")

st.divider()

# ---------- 2. 延迟分解表 ----------
st.subheader("⏱️ 检索链路延迟分解")
rows = []
for m in metrics:
    spans = m["spans"]
    rows.append(
        {
            "query": (m["query"] or "")[:40],
            "总延迟(s)": round(m["total_latency"], 3),
            "retrieve(s)": round(spans.get("retrieve", {}).get("latency", 0), 3),
            "rerank(s)": round(spans.get("rerank", {}).get("latency", 0), 3),
            "generate(s)": round(spans.get("generate", {}).get("latency", 0), 3),
            "模型": spans.get("generate", {}).get("model", ""),
            "tokens": spans.get("generate", {}).get("usage", {}).get("total", 0),
        }
    )

try:
    import pandas as pd

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, height=420)

    # 延迟分布条形图（用 pandas 直接画太丑，改用简单文本/表格）
    st.subheader("📈 各环节平均延迟")
    avg_retrieve = sum(r["retrieve(s)"] for r in rows) / total
    avg_rerank = sum(r["rerank(s)"] for r in rows) / total
    avg_generate = sum(r["generate(s)"] for r in rows) / total
    chart = pd.DataFrame(
        {
            "环节": ["retrieve", "rerank", "generate"],
            "平均延迟(s)": [round(avg_retrieve, 3), round(avg_rerank, 3), round(avg_generate, 3)],
        }
    )
    st.bar_chart(chart.set_index("环节"))
except ImportError:
    st.warning("未安装 pandas，跳过表格展示")
    for r in rows:
        st.write(r)

st.divider()

# ---------- 3. 查询历史 ----------
st.subheader("💬 最近查询")
for m in list(reversed(metrics))[:10]:
    label = (m["query"] or "(无 query)")[:60]
    with st.expander(f"Q: {label}  ·  {m['total_latency']:.2f}s"):
        st.markdown(f"**A:** {(m['answer'] or '')[:500]}")
        g = m["spans"].get("generate", {})
        st.caption(
            f"模型 {g.get('model', '?')} · "
            f"tokens {g.get('usage', {}).get('total', 0)} · "
            f"retrieve {m['spans'].get('retrieve', {}).get('latency', 0):.2f}s / "
            f"rerank {m['spans'].get('rerank', {}).get('latency', 0):.2f}s / "
            f"generate {g.get('latency', 0):.2f}s"
        )
