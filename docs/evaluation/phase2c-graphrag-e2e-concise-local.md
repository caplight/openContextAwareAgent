# Phase 2c — Graph-RAG 端到端（LightRAG local 图推理，简洁版 prompt）

- 评测集：HotpotQA distractor 验证集，20 条（前 20 条）
- 检索库：golden corpus 前 200 段（候选池 200）
- 生成：LightRAG `local` 图推理（实体关系链 + 社区摘要 + chunks），only_need_context=False
- 生成风格：自定义简洁 system_prompt（只给最终答案，无 Markdown/References），enable_llm_cache=False
- LLM judge：deepseek-chat

> 注：这是「端到端 GraphRAG」（图推理生成答案），区别于「隔离检索」（只取 chunks 喂通用生成器）。

| 指标 | 分数 |
|------|------|
| answer_correctness | 0.6450 |
| faithfulness | 0.7167 |
| context_precision | 0.4110 |
| gold_recall | 0.7000 |
