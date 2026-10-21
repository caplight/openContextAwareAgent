# Enterprise Knowledge Base Assistant (RAG demo)

> Upload documents → ask questions in natural language. A production-grade RAG reference that proves three things:
> **retrieval quality that actually holds up**, **cost and latency you can budget for**, and **end-to-end observability**.

## Tech Stack

| Layer | Choice |
|---|---|
| Orchestration | LangGraph |
| Vector DB | Qdrant (local mode, no docker needed) |
| Embedding | bge-m3 (local) |
| Reranker | BGE Reranker v2-m3 (local) |
| Generation | DeepSeek Flash (primary) + Claude Haiku 5.5 (fallback), LiteLLM routing |
| Graph-RAG | LightRAG |
| Observability | Langfuse (self-hosted docker, v4 SDK) |
| Simulated backend | KWOK (Phase 3 — cluster state source) |
| Backend / Frontend | FastAPI + Streamlit |
| Evaluation | RAGAS + HotpotQA |

## Project Structure

```
demo/
├── pyproject.toml              # metadata + deps + ruff/pytest/mypy
├── src/enterprise_kb/          # source package
│   ├── config.py               # centralized config (pydantic-settings)
│   ├── llm.py                  # LiteLLM wrapper (primary → fallback)
│   ├── ingest.py               # document loading + chunking
│   ├── embed.py                # bge-m3 embedding + Qdrant storage
│   ├── retrieve.py             # hybrid recall (dense + BM25 + RRF)
│   ├── hybrid.py               # BM25 + dense + RRF fusion
│   ├── rerank.py               # bge-reranker-v2-m3 re-ranking
│   ├── generate.py             # RAG prompt + generation
│   ├── graph.py                # LangGraph (retrieve → rerank → generate)
│   ├── tracing.py              # Langfuse tracing (root + node spans)
│   ├── observability.py        # pull Langfuse API for the dashboard
│   ├── api.py                  # FastAPI
│   └── cli.py                  # CLI (kb ingest)
├── tests/                      # pytest
├── frontend/streamlit_app.py   # Q&A frontend
├── frontend/dashboard.py       # observability dashboard (:8502)
├── eval/                       # HotpotQA + RAGAS
└── data/docs/                  # demo corpus (K8s + AWS docs)
```

## Quick Start

### 1. Install dependencies

```bash
uv sync --extra dev --extra eval
```

> On the shared mount (`/mnt/hgfs`) add `UV_LINK_MODE=copy` — vmhgfs-fuse doesn't support symlinks.

### 2. Inject API keys (env vars only, never written to disk)

```bash
export DEEPSEEK_API_KEY=sk-xxx        # current primary
# optional: export ANTHROPIC_API_KEY=sk-xxx
```

> Keys live in environment variables; `.env` never stores real keys (gitignored).

### 3. Ingest documents + build the index

```bash
uv run kb ingest
```

### 4. Run the API + frontend

```bash
uv run uvicorn enterprise_kb.api:app --reload
uv run streamlit run frontend/streamlit_app.py
```

### 5. Run tests

```bash
uv run pytest
uv run ruff check .
```

## Phases

| Phase | What | Status |
|---|---|---|
| Phase 1 | Naive RAG baseline (vector retrieval + generation) | ✅ done |
| Phase 2 | Hybrid retrieval (BM25+dense) + reranker + Graph-RAG (LightRAG) | ✅ done |
| Phase 3 | Simulated cluster backend (KWOK) + DevOps assistant | 🚧 in progress — see [`docs/kwok.md`](docs/kwok.md) |
| Phase 4 | Observability (Langfuse) + hybrid/rerank on main path + dashboard | ✅ done |

## Phase 1 Module Map

- M1.1 Document ingestion → `ingest.py`
- M1.2 Embedding + storage → `embed.py`
- M1.3 Retrieval → `retrieve.py`
- M1.4 Generation → `generate.py`
- M1.5 API + frontend → `api.py` + `frontend/`
- M1.6 Evaluation baseline → `eval/`
- M1.7 Observability → `tracing.py`

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — design & data flow
- [`docs/kwok.md`](docs/kwok.md) — simulated cluster backend (Phase 3)
- [`docs/kpi.md`](docs/kpi.md) — cost & latency KPIs
- [`docs/conclusions.md`](docs/conclusions.md) — Phase 2 findings
- [`docs/decisions/`](docs/decisions/) — ADRs

> 中文版见 [README.zh-CN.md](README.zh-CN.md) · Chinese version: [README.zh-CN.md](README.zh-CN.md)
