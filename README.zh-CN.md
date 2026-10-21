# 企业知识库智能助手（RAG demo）

> 上传文档 → 自然语言问答。一个「生产级」RAG 参考实现，想证明三件事：**检索质量经得起推敲**、**成本/延迟心里有数**、**全程可观测**。

## 技术栈

| 环节 | 选型 |
|---|---|
| 编排 | LangGraph |
| 向量库 | Qdrant（local mode，无需 docker） |
| Embedding | bge-m3（本地） |
| Reranker | BGE Reranker v2-m3（本地） |
| 生成 | DeepSeek Flash 主力 + Claude Haiku 5.5 备选（LiteLLM 路由） |
| Graph-RAG | LightRAG |
| 可观测 | Langfuse（自托管 docker，v4 SDK） |
| 模拟后端 | KWOK（Phase 3 — 集群状态源） |
| 后端 / 前端 | FastAPI + Streamlit |
| 评测 | RAGAS + HotpotQA |

## 项目结构

```
demo/
├── pyproject.toml              # 元数据 + 依赖 + ruff/pytest/mypy
├── src/enterprise_kb/          # 源码包
│   ├── config.py               # 集中配置（pydantic-settings）
│   ├── llm.py                  # LiteLLM 封装（primary → fallback 降级）
│   ├── ingest.py               # 文档摄入 + 分块
│   ├── embed.py                # bge-m3 向量化 + Qdrant 存储
│   ├── retrieve.py             # hybrid 召回（dense + BM25 + RRF）
│   ├── hybrid.py               # BM25 + dense + RRF 融合
│   ├── rerank.py               # bge-reranker-v2-m3 精排
│   ├── generate.py             # RAG prompt + 生成
│   ├── graph.py                # LangGraph 编排（retrieve → rerank → generate）
│   ├── tracing.py              # Langfuse 埋点（root + 节点 span）
│   ├── observability.py        # 拉 Langfuse API 供 dashboard 消费
│   ├── api.py                  # FastAPI
│   └── cli.py                  # CLI（kb ingest）
├── tests/                      # pytest
├── frontend/streamlit_app.py   # Q&A 前端
├── frontend/dashboard.py       # 可观测 dashboard（:8502）
├── eval/                       # HotpotQA + RAGAS
└── data/docs/                  # 演示语料（K8s + AWS 官方文档）
```

## 快速开始

### 1. 装依赖

```bash
uv sync --extra dev --extra eval
```

> 共享目录（`/mnt/hgfs`）要加 `UV_LINK_MODE=copy`（vmhgfs-fuse 不支持 symlink）。

### 2. 注入 API key（只走环境变量，不落盘）

```bash
export DEEPSEEK_API_KEY=sk-xxx        # 当前主力
# 可选：export ANTHROPIC_API_KEY=sk-xxx
```

> key 只放环境变量，`.env` 不存真实 key（已 gitignore）。

### 3. 摄入文档 + 建索引

```bash
uv run kb ingest
```

### 4. 起 API + 前端

```bash
uv run uvicorn enterprise_kb.api:app --reload
uv run streamlit run frontend/streamlit_app.py
```

### 5. 跑测试

```bash
uv run pytest
uv run ruff check .
```

## Phase 进度

| Phase | 内容 | 状态 |
|---|---|---|
| Phase 1 | Naive RAG 基线（向量检索 + 生成） | ✅ 完成 |
| Phase 2 | 混合检索（BM25+dense）+ reranker + Graph-RAG（LightRAG） | ✅ 完成 |
| Phase 3 | 模拟集群后端（KWOK）+ DevOps 助手 | 🚧 进行中 — 见 [`docs/kwok.md`](docs/kwok.md) |
| Phase 4 | 可观测（Langfuse）+ hybrid/rerank 接主线 + dashboard | ✅ 完成 |

## Phase 1 模块映射

- M1.1 文档摄入 → `ingest.py`
- M1.2 向量化 + 存储 → `embed.py`
- M1.3 检索 → `retrieve.py`
- M1.4 生成 → `generate.py`
- M1.5 API + 前端 → `api.py` + `frontend/`
- M1.6 评测基线 → `eval/`
- M1.7 可观测 → `tracing.py`

## 文档

- [`docs/architecture.md`](docs/architecture.md) — 架构与数据流
- [`docs/kwok.md`](docs/kwok.md) — 模拟集群后端（Phase 3）
- [`docs/kpi.md`](docs/kpi.md) — 成本与延迟 KPI
- [`docs/conclusions.md`](docs/conclusions.md) — Phase 2 结论
- [`docs/decisions/`](docs/decisions/) — 架构决策记录（ADR）
