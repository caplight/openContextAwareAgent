"""Streamlit 前端：复用后端逻辑（同进程），快速出可交互 demo。

支持中英双语切换（sidebar 顶部）。
"""

import streamlit as st

from enterprise_kb.graph import ask
from locales import lang_selector, make_t

st.set_page_config(page_title="Enterprise KB Assistant", page_icon="📚")

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
    st.markdown(f"**{t('answer_prefix')}** {item['answer']}")
    st.caption(f"{t('app_model_label')}: {item['model']}")
    with st.expander(f"{t('app_contexts_label')}（{len(item['contexts'])} {t('app_segments_label')}）"):
        for i, ctx in enumerate(item["contexts"], 1):
            st.markdown(f"**[{i}]** {ctx}")
    st.divider()
