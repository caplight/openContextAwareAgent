# Phase 1 — naive RAG baseline（RAGAS）

- 评测集：HotpotQA distractor 验证集，50 条（固定 50 条，见 README.md）
- 检索：bge-m3 向量 top-3（内存检索）
- 生成：deepseek/deepseek-flash
- LLM judge：deepseek-chat

| 指标 | 分数 |
|------|------|
| faithfulness | 0.9410 |
| context_precision | 0.5183 |
