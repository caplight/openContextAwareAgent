# Phase 2c — Graph-RAG（LightRAG）hybrid

- 评测集：HotpotQA distractor 验证集，50 条（前 50 条）
- 检索库：golden corpus 前 492 段（候选池 492，= 50 条问题的完整 context）
- 检索：LightRAG `hybrid` 模式 top-20（无 rerank）（only_need_context=True，enable_rerank=False）
- 生成：deepseek/deepseek-flash；LLM judge：deepseek-chat

> 注：2c 是 492 段候选池，与 2a/2b 的 1991 段不可直接比数字，仅看趋势。

| 指标 | 分数 |
|------|------|
| answer_correctness | 0.6338 |
| faithfulness | 0.9871 |
| context_precision | 0.4552 |
