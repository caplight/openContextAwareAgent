# Phase 1 — naive RAG baseline（RAGAS）

- 评测集：HotpotQA distractor 验证集，20 条
- 检索：bge-m3 向量 top-3（内存检索）
- 生成：deepseek/deepseek-flash（fallback）
- LLM judge：deepseek-chat

| 指标 | 分数 |
|------|------|
| faithfulness | 0.9025 |
| context_precision | 0.4708 |

> 说明：这是 naive RAG 的基线，Phase 2 用混合检索 + rerank + Graph-RAG 后与此对比。