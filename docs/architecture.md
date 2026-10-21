# 架构设计

## 1. 设计目标

证明一个「生产级」RAG 系统应该怎么做——不是调个 API 拼字符串，而是：

1. **分层清晰**：config → ingest → embed → retrieve → generate，每层可独立测试、可替换
2. **编排可演化**：用 LangGraph 状态图，节点可插拔（Phase 2/3 加 rerank、路由、降级不改核心）
3. **可观测内置**：LLM 调用带 token 用量，trace 全程可回溯（成本 KPI 的数据来源）

## 2. 模块划分（src/enterprise_kb/）

| 模块 | 职责 | 关键点 |
|------|------|--------|
| `config.py` | 集中配置 | pydantic-settings，嵌套模型 + `env_nested_delimiter="__"` + lru_cache 单例 |
| `llm.py` | LLM 路由 | LiteLLM 封装，primary→fallback 自动降级，`LLMResult` 带 token 用量 |
| `ingest.py` | 文档摄入 | loader + chunker（chunk 512 / overlap 51） |
| `embed.py` | 向量化 + 存储 | bge-m3（1024 维），Qdrant local mode |
| `retrieve.py` | 召回 | hybrid 召回（dense bge-m3 + BM25 + RRF）→ 候选池 |
| `hybrid.py` | 混合检索 | BM25（bm25s）+ dense + RRF 等权融合（RRF_K=60） |
| `rerank.py` | 精排 | bge-reranker-v2-m3（CrossEncoder）top-k |
| `generate.py` | 生成 | RAG prompt（引用 `[n]`）+ LLM |
| `graph.py` | 编排 | LangGraph 状态图（retrieve → rerank → generate） |
| `tracing.py` | 可观测 | Langfuse v4 SDK，root trace + 节点 span（token/延迟） |
| `observability.py` | 观测数据 | 拉 Langfuse REST API，供 Streamlit dashboard 消费 |
| `api.py` | FastAPI | /ingest /query /health |
| `cli.py` | CLI | `kb ingest` |

## 3. 数据流（Phase 4 当前实现：召回 → 精排 → 生成）

```
文档(data/docs)
   │  ingest.py（loader + chunker）
   ▼
chunks (843)
   │  embed.py（bge-m3 → 1024 维向量）
   ▼
Qdrant (local mode)
   ▲
   │
用户提问 ──► graph.ask()  ── 外层 rag-query root trace（Langfuse chain）
              │
              ▼
           retrieve_node（span: retriever）
              │  hybrid 召回：dense（Qdrant bge-m3）+ BM25（bm25s）
              │  RRF 等权融合（RRF_K=60）→ 候选池（实测 ~36 个）
              ▼
           rerank_node（span: span）
              │  bge-reranker-v2-m3（CrossEncoder）精排 → top-k（=5）
              ▼
           generate_node（span: generation，回填 token + model）
              │  RAG prompt（引用 [n]）→ LLM（deepseek-flash）
              ▼
           LLMResult（answer + model + tokens）→ tracing.flush()
```

> 关键：hybrid 的价值不在「直接输出 top-3」（单独用反降），而在「提供更全候选池给 reranker」。
> 正确链路 = 「召回 → 精排」。

## 4. LLM 分层降级

```
primary: claude-haiku-5-5（质量优先，需要 ANTHROPIC_API_KEY）
   │  失败 / 未配 key
   ▼
fallback: deepseek/deepseek-flash（便宜，国内可直连）
```

- 当前环境未配 Anthropic key → 自动 fallback 到 DeepSeek（已验证）
- 单次查询成本 < $0.01（KPI #2）

## 5. 演进路线

| Phase | 内容 | 状态 |
|-------|------|------|
| **Phase 1** | naive RAG 基线（向量检索 + LLM 生成） | ✅ 完成（含 RAGAS baseline，见 docs/evaluation/） |
| **Phase 2** | 混合检索（BM25+dense）+ Reranker + Graph-RAG（LightRAG） | ✅ 完成（结论见 docs/conclusions.md） |
| **Phase 3** | 模拟 EKS backend + DevOps 助手（贴近求职方向） | 🔜 |
| **Phase 4** | 可观测（Langfuse 自托管）+ hybrid/rerank 接主线 + Streamlit dashboard | ✅ 完成（本文件当前态） |

## 6. 关键设计决策

详见 `docs/decisions/`（ADR 格式），包括：
- Embedding 选 bge-m3 的理由
- LLM 选 Claude Haiku 5.5 + DeepSeek 备选的理由
- 向量库选 Qdrant（local mode）的理由
- torch CPU 版（当前无 GPU 环境）的约束

## 7. 环境约束（当前 VM）

- **无 GPU**：VMware Workstation 桌面版不支持 NVIDIA GPU 直通，`torch` 用 CPU 版
- **数据盘**：`/data`（40G sdb1），venv / 模型 / cache / Qdrant 都迁到这里
- **共享目录**：项目代码在 `/mnt/hgfs`（vmhgfs-fuse，不支持 symlink）
- **代理**：运行时 `unset ALL_PROXY`（socks 不被 httpx 支持），http 代理供外网访问

## 8. 可观测（Phase 4 新增）

### 8.1 Langfuse 自托管

- 部署在 `/data/langfuse`（docker compose，6 容器：postgres / redis / minio / clickhouse / web / worker）
- 凭据 `/data/langfuse/keys.txt`（PK / SK / admin），HOST `http://localhost:3000`
- SDK 用 langfuse v4（4.17.0，OTel 底层），走 legacy `/api/public/ingestion`，需 `LANGFUSE_MIGRATION_V4_WRITE_MODE=dual` 兼容

### 8.2 trace 埋点（tracing.py）

- `ask()` 外层包 `rag-query` root trace（chain），graph 节点内用 `trace()` 埋 span
- 4 个 span：`rag-query`（chain）/ `retrieve`（retriever）/ `rerank`（span）/ `generate`（generation）
- `generate` span 通过 `span.update(usage_details=..., cost_details=..., model=...)` 回填 token、成本与模型
- 追踪失败 try/except 静默 no-op，不影响主流程

### 8.3 观测数据 + dashboard

- `observability.py`：requests 调 Langfuse REST API（basic auth PK:SK），`GET /api/public/traces/:id` 内联 observation 详情
- `frontend/dashboard.py`：Streamlit，展示汇总指标卡 / 延迟分解表（retrieve·rerank·generate 三段）/ 查询历史
- 启动：`streamlit run frontend/dashboard.py --server.port 8502`

## 9. 部署踩坑（Langfuse 自托管，可复用）

1. **镜像 DNS 污染**：`registry-1.docker.io` 被污染到 Twitter 段，docker daemon 配代理（systemd drop-in）解决
2. **containerd 快照未随 data-root 迁移**：根分区爆满，`ln -s /data/containerd /var/lib/containerd`
3. **v4 events_only 拒 legacy 事件**：compose environment 显式加 `LANGFUSE_MIGRATION_V4_WRITE_MODE`
4. **huggingface_hub 联网重试拖慢启动**：`__init__.py` 设 `HF_HUB_OFFLINE=1` + `TRANSFORMERS_OFFLINE=1`（527s → 67s）
