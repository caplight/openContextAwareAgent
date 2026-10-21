# Phase 2c — Graph-RAG（LightRAG）global + rerank

- 评测集：HotpotQA distractor 验证集，20 条（前 20 条）
- 检索库：golden corpus 前 200 段（候选池 200，= 20 条问题各 10 段完整 context）
- 检索：LightRAG `global` top-20 → bge-reranker-v2-m3 精排 top-3（only_need_context=True，enable_rerank=False）
- 生成：deepseek/deepseek-flash；LLM judge：deepseek-chat

> 注：2c 是 200 段候选池，与 2a/2b 的 1991 段不可直接比数字，仅看趋势。

| 指标 | 分数 |
|------|------|
| answer_correctness | 0.5156 |
| faithfulness | 0.9704 |
| context_precision | 0.4667 |
