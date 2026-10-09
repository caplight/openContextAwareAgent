# ADR-001：Embedding 选 bge-m3

- **状态**：已采纳（定稿）
- **日期**：2026-10

## 背景（Context）

需要选一个 embedding 模型做文档向量化。候选包括 OpenAI text-embedding-3、Cohere embed、以及开源本地模型（bge 系列、GTE、E5 等）。

约束：
- 自托管优先、0 边际成本、可离线（demo 录屏不依赖外部 API）
- 中文 + 英文混合语料要都能处理
- 检索质量要能支撑「准确率 90%」的 KPI

## 决策（Decision）

选 **BAAI/bge-m3**：
- 1024 维向量
- 多语言（中英）+ 多粒度（dense + sparse + multi-vector）
- 本地加载（`SentenceTransformer`），无需外部 API

## 理由（Rationale）

1. **0 成本**：本地推理，不按 token 计费（对比 OpenAI embedding 要花钱）
2. **MTEB 榜上有名**：bge-m3 在检索类任务上是开源第一梯队
3. **可离线**：demo 录屏不依赖网络
4. **为 Phase 2 留口子**：bge-m3 本身支持 sparse/多向量，混合检索时不用换模型

## 后果（Consequences）

- 正面：成本 0、离线、多语言
- 负面：CPU 推理慢（单条 ~2s，无 GPU 环境）；模型 2.2G 需本地存放
- 配套：Reranker 选 BGE Reranker v2-m3（同族，Phase 2 接入）
