# ADR-003：向量库选 Qdrant（local mode）

- **状态**：已采纳（定稿）
- **日期**：2026-10

## 背景（Context）

向量库候选：Qdrant、Milvus、Weaviate、Pinecone、Chroma、FAISS。

约束：
- 当前 VM 未装 docker
- 自托管优先、0 边际成本
- demo 阶段数据量小（几百 ~ 几千 chunks）

## 决策（Decision）

选 **Qdrant**，用 **local mode**（嵌入式，路径持久化，无需 docker/服务）。

## 理由（Rationale）

1. **local mode 免 docker**：直接 `QdrantClient(path=...)`，零运维
2. **Rust 实现**：性能好，后续上生产可直接切 server 模式（同一 API）
3. **过滤 + 混合检索支持**：Phase 2 加 BM25 + rerank 时不用换库
4. 对比 Milvus（重，需 docker）、Pinecone（托管，花钱）、Chroma（能力较弱）

## 后果（Consequences）

- 正面：零成本、零运维、可迁移 server 模式
- 负面：local mode 并发能力有限（demo 够用）
- 坑：qdrant-client 1.19 移除了 `search` 方法，改用 `query_points`
