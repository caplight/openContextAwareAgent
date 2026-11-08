"""Streamlit 前端：Kubernetes DevOps 助手（ReAct agent 复用后端逻辑）。

agent 自主决定「查集群（k8s_*）/ 查文档（kb_search）/ 联网（web_search）」取证，
前端展示最终回答 + 工具调用轨迹（可观测）。
支持中英双语切换（sidebar 顶部）。
"""

import streamlit as st

from enterprise_kb.agent import ask
from locales import lang_selector, make_t

st.set_page_config(page_title="Kubernetes DevOps Assistant", page_icon="📚")

lang = lang_selector()
t = make_t(lang)

st.title(t("app_title"))
st.caption(t("app_caption"))

if "history" not in st.session_state:
    st.session_state.history = []

query = st.text_input(
    t("app_input_label"),
    placeholder=t("app_input_placeholder"),
)

if st.button(t("app_ask")) and query:
    with st.spinner(t("app_spinner")):
        result = ask(query)
    tool_trace = []
    for m in result.get("messages", []):
        if getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                tool_trace.append(f"{tc.get('name')}({tc.get('args')})")
    st.session_state.history.append(
        {
            "query": query,
            "answer": result["answer"],
            "tool_trace": tool_trace,
        }
    )

for item in reversed(st.session_state.history):
    st.markdown(f"**Q:** {item['query']}")
    st.markdown(f"**{t('answer_prefix')}** {item['answer']}")
    if item.get("tool_trace"):
        with st.expander(f"{t('app_tool_trace_label')}（{len(item['tool_trace'])} {t('app_tool_calls')}）"):
            for i, tr in enumerate(item["tool_trace"], 1):
                st.markdown(f"**[{i}]** `{tr}`")
    st.divider()
