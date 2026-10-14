# Phase 2b — 混合检索 + bge-reranker-v2-m3（golden corpus）

- 评测集：HotpotQA distractor 验证集，50 条（固定 50 条）
- 检索库：共享 golden corpus，1991 段（候选池 ~1991，非每条 10 段）
- top_k=3，reranker top_n=20，RRF candidate factor=4
- 生成：deepseek/deepseek-flash；LLM judge：deepseek-chat

| 指标 | 分数 |
|------|------|
| faithfulness | 0.9692 |
| context_precision | 0.5733 |
| gold_recall@3 | 0.9400 |
