"""Streamlit 前端：复用后端逻辑（同进程），快速出可交互 demo。"""

import streamlit as st

from enterprise_kb.graph import ask

st.set_page_config(page_title="企业知识库智能助手", page_icon="📚")
st.title("📚 企业知识库智能助手")
st.caption("Phase 1 — naive RAG 基线（向量检索 + LLM 生成）")

if "history" not in st.session_state:
    st.session_state.history = []

query = st.text_input(
    "输入你的问题",
    placeholder="e.g. How do I scale a Kubernetes deployment?",
)

if st.button("提问") and query:
    with st.spinner("检索 + 生成中…"):
        result = ask(query)
    st.session_state.history.append(
        {
            "query": query,
            "answer": result["answer"],
            "contexts": result["contexts"],
            "model": result.get("model", ""),
        }
    )

for item in reversed(st.session_state.history):
    st.markdown(f"**Q:** {item['query']}")
    st.markdown(f"**A:** {item['answer']}")
    st.caption(f"模型：{item['model']}")
    with st.expander(f"引用上下文（{len(item['contexts'])} 段）"):
        for i, ctx in enumerate(item["contexts"], 1):
            st.markdown(f"**[{i}]** {ctx}")
    st.divider()
