# 企业知识库智能助手（RAG demo）

> 用户上传文档 → 自然语言问答。证明三件事：**检索质量硬、成本/延迟可控、全程可观测**。

## 技术栈（已定稿）

| 环节 | 选型 |
|---|---|
| 编排 | LangGraph |
| 向量库 | Qdrant（默认 local mode，无需 docker） |
| Embedding | bge-m3（本地） |
| Reranker | BGE Reranker v2-m3（Phase 2 接入） |
| 生成 LLM | Claude Haiku 5.5 主力 + DeepSeek V4.1 Flash 备选（LiteLLM 路由） |
| Graph-RAG | LightRAG（Phase 2 接入） |
| 可观测 | Langfuse |
| 后端/前端 | FastAPI + Streamlit |
| 评测 | RAGAS + HotpotQA |

## 项目结构（src layout，业界标准）

```
demo/
├── pyproject.toml          # 项目元数据 + 依赖 + ruff/pytest/mypy 配置
├── src/enterprise_kb/      # 源码包
│   ├── config.py           # 集中配置（pydantic-settings）
│   ├── llm.py              # LiteLLM 封装（primary→fallback 降级）
│   ├── ingest.py           # 文档摄入（loader + chunker）
│   ├── embed.py            # bge-m3 向量化 + Qdrant 存储
│   ├── retrieve.py         # 纯向量 top-k 检索
│   ├── generate.py         # RAG prompt + 生成
│   ├── graph.py            # LangGraph 编排
│   ├── tracing.py          # Langfuse trace
│   ├── api.py              # FastAPI
│   └── cli.py              # CLI（kb ingest）
├── tests/                  # pytest 单元测试
├── frontend/streamlit_app.py
├── eval/                   # HotpotQA + RAGAS 评测
└── data/docs/              # 演示文档（K8s + AWS 官方文档）
```

## 快速开始

### 1. 装依赖（uv）

```bash
uv sync --extra dev --extra eval
```

> 共享目录（/mnt/hgfs）需加 `UV_LINK_MODE=copy`（不支持 symlink）。

### 2. 注入 API key（环境变量，不落盘）

```bash
export DEEPSEEK_API_KEY=sk-xxx        # 当前主力（爸爸猫在中国，先不配 Claude）
# 可选：export ANTHROPIC_API_KEY=sk-xxx
```

> key 只走环境变量，`.env` 不存真实 key（`.gitignore` 已忽略）。

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
uv run ruff check .   # lint
```

## Phase 1 模块映射

- M1.1 文档摄入 → `ingest.py`
- M1.2 向量化 + 存储 → `embed.py`
- M1.3 检索 → `retrieve.py`
- M1.4 生成 → `generate.py`
- M1.5 API + 前端 → `api.py` + `frontend/`
- M1.6 评测基线 → `eval/`
- M1.7 可观测 → `tracing.py`
