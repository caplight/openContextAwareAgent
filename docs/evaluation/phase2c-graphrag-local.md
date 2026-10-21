# Phase 2c — Graph-RAG（LightRAG）local 模式

- 评测集：HotpotQA distractor 验证集，20 条（前 20 条）
- 检索库：golden corpus 前 200 段（候选池 200，= 20 条问题各 10 段完整 context）
- 检索：LightRAG `local` 模式，only_need_context=True，enable_rerank=False
- 生成：deepseek/deepseek-flash；LLM judge：deepseek-chat

> 注：2c 是 200 段候选池 + LightRAG 多 chunk 召回（chunk_top_k≈20），与 2a/2b 的 1991 段 + top-3 不可直接比数字，仅看趋势。

| 指标 | 分数 |
|------|------|
| answer_correctness | 0.6334 |
| faithfulness | 0.9192 |
| context_precision | 0.4153 |
