# Phase 2b — 混合检索 + Reranker（RAGAS）

- 评测集：HotpotQA distractor 验证集，50 条（固定 50 条，见 README.md）
- 检索：BM25 + bge-m3 dense + RRF 融合 → bge-reranker-v2-m3 精排 → top-3
- 生成：deepseek/deepseek-flash
- LLM judge：deepseek-chat

| 指标 | 分数 |
|------|------|
| faithfulness | 0.9504 |
| context_precision | 0.5967 |
