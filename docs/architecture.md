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
| `retrieve.py` | 检索 | Phase 1 纯向量 top-k |
| `generate.py` | 生成 | RAG prompt（引用 `[n]`）+ LLM |
| `graph.py` | 编排 | LangGraph 状态图（retrieve → generate） |
| `tracing.py` | 可观测 | Langfuse trace |
| `api.py` | FastAPI | /ingest /query /health |
| `cli.py` | CLI | `kb ingest` |

## 3. 数据流（Phase 1 naive RAG）

```
文档(data/docs)
   │  ingest.py（loader + chunker）
   ▼
chunks (843)
   │  embed.py（bge-m3 → 1024 维向量）
   ▼
Qdrant (local mode)
   ▲
   │  retrieve.py（向量 top-k）
   │
用户提问 ──► graph.ask()
              │  retrieve_node：query → 向量 → top-5 chunks
              ▼
           generate_node：RAG prompt → LLM → 答案（引用 [n]）
              │
              ▼
           LLMResult（answer + model + tokens）→ tracing
```

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
| **Phase 2** | 混合检索（BM25+dense）+ Reranker + Graph-RAG（LightRAG） | 🔜 进行中 |
| **Phase 3** | 模拟 EKS backend + DevOps 助手（贴近求职方向） | 🔜 |

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
