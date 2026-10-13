# Phase 2a — 混合检索 BM25+dense+RRF（RAGAS）

- 评测集：HotpotQA distractor 验证集，50 条（固定 50 条，见 README.md）
- 检索：BM25（bm25s）+ bge-m3 dense + RRF 融合（k=60），top-3
- 生成：deepseek/deepseek-flash
- LLM judge：deepseek-chat

| 指标 | 分数 |
|------|------|
| faithfulness | 0.9371 |
| context_precision | 0.5800 |
