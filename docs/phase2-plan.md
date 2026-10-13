# Phase 2 拆解蓝图

> 目标：把 `context_precision` 从 Phase 1 的 **47.08%** 拉到 **60~70%**（faithfulness 已达标 90%，不动）。
> 原则：每一步独立可测、可对比，形成「baseline → 混合检索 → rerank → Graph-RAG」的演进曲线。

## 分三个子阶段（按投入产出比 + 依赖排序）

| 子阶段 | 手段 | 成本 | 预期收益 | 依赖 |
|--------|------|------|----------|------|
| **2a** | 混合检索（dense + sparse + RRF） | 低 | 关键词精确 + 语义互补，基础提升 | 无 |
| **2b** | Reranker（bge-reranker-v2-m3 精排） | 中 | 候选精排，再提一截 | 2a |
| **2c** | Graph-RAG（LightRAG 实体关系图） | 高 | 多跳推理问题显著提升（HotpotQA 正是多跳数据集） | 2a/2b |

## Phase 2a — 混合检索（hybrid search）

**核心洞察**（调研确认）：Qdrant **不支持原生 BM25**，但 bge-m3 单次前向即可输出 `dense`（1024 维）+ `sparse`（BM25 式稀疏向量）+ `colbert`（multi-vector）三种表示。因此混合检索 = bge-m3 dense + bge-m3 sparse 双路，Qdrant 用 **RRF（Reciprocal Rank Fusion）** 融合。

**改动点**：
1. `embed.py`：`encode()` 增加 sparse 输出；`index_chunks()` 写入时同时存 dense + sparse 两个 vector
2. `config.py`：Qdrant collection 需声明 sparse vector 配置（`sparse_vectors_config`）
3. `retrieve.py`：改用 `query_points` 的 `prefetch` + `FusionQuery(fusion=RRF)`，dense 和 sparse 各取 top-N 再融合

**RRF 公式**：`score(d) = Σ 1/(k + rank_i(d))`，k 默认 60。只依赖排名，不比较原始分数（dense/sparse 分数不可比）。

**验证**：`eval/eval_ragas.py` 跑同一 50 条测试集，对比 context_precision。

## Phase 2b — Reranker

**模型**：`BAAI/bge-reranker-v2-m3`（CrossEncoder，本地 Apache-2.0，与 bge-m3 同生态，多语言）。

```python
from sentence_transformers import CrossEncoder
model = CrossEncoder("BAAI/bge-reranker-v2-m3")
scores = model.predict([(query, doc) for doc in candidates])  # 返回相关性分数
```

**改动点**：
1. 下载模型到 `/data/models/bge-reranker-v2-m3`（约 2G）
2. 新增 `rerank.py`：混合检索取 top-N（如 20）候选 → reranker 精排 → top-k（如 5）
3. `graph.py`：retrieve 节点后插入 rerank 节点（LangGraph 状态图的价值：节点可插拔）

## Phase 2c — Graph-RAG（LightRAG）

**框架**：LightRAG（HKUDS，EMNLP 2025，v1.5.3，36K+ stars）。
- 把文档切小块 → LLM 抽取实体 + 关系 → 构建知识图谱
- 查询支持 `local`（实体邻居）/ `global`（社区摘要）/ `hybrid` 三种模式
- 需要 embedding func + LLM func（DeepSeek 兼容 OpenAI 接口）
- 存储：KV storage（本地 JSON 即可，无需 Redis）

**为什么这一步对 HotpotQA 最关键**：HotpotQA 是**多跳推理**数据集（需跨文档找实体关系），Graph-RAG 正是解决「跨文档实体关系」问题的强项，预计是 context_precision 提升最大的一步。

**改动点**：
1. `pyproject.toml` 加 `lightrag-hku` 依赖
2. 新增 `graphrag.py`：封装 LightRAG 的 insert + query
3. 评测脚本加 Graph-RAG 分支（local/global/hybrid 三种模式对比）

---

## 依赖新增清单

| 子阶段 | 新增依赖 | 模型下载 |
|--------|----------|----------|
| 2a | 无（bge-m3 已含 sparse） | 无 |
| 2b | `sentence-transformers`（已有） | `BAAI/bge-reranker-v2-m3`（~2G） |
| 2c | `lightrag-hku` | 无（复用 bge-m3 + DeepSeek） |

## 评测与对比协议

- 每步跑完 → `docs/evaluation/phase2{N}-{名称}.md` + 更新 `docs/evaluation/README.md` 汇总表
- 固定：50 条测试集 + `deepseek-chat` judge + `faithfulness`/`context_precision` 指标
- 演进曲线：Phase1(47%) → 2a → 2b → 2c，面试可直接引用每一步的 delta
