# per-assistant config 架构拆解

- **状态**：草案 v0.1
- **日期**：2026-11-18
- **依赖**：`docs/mvp-design.md`（§2.2 assistant_config）
- **目标**：把「全局 `Settings` → 每助手一份配置」这个前置架构改动拆细，明确字段分类、数据模型、存储、加载、迁移路径。

---

## 1. 核心原则：最小侵入、渐进式

现有 `get_settings()` 被 **61 处**引用（`src/` + `eval/` + `tests/`），是全局 `@lru_cache` 单例。**不能一次性重构**。

**方案**：保留全局 `Settings`（部署级，每台机器一份），新增 `AssistantConfig`（助手级，每助手一份），用 `load_assistant_config(assistant_id)` 桥接——**默认回退到全局 Settings 的对应字段，有助手级覆盖就用助手级**。

---

## 2. 字段分类（部署级 vs 助手级）

现有 `Settings` 字段分成两类：

### 2.1 部署级（保持全局，不进 AssistantConfig）

这些是「一台机器 / 一次部署」级别的，与单个助手无关：

| 字段 | 为什么是部署级 |
|---|---|
| `qdrant.url / path / collection` | 向量库底层实例连接（选哪个库是助手级，怎么连是部署级） |
| `embedding.dim / device / normalize` | 本地 bge-m3 的技术参数 |
| `context.max_tokens / keep_turns` | 上下文压缩策略（历史超限时） |
| `reranker.model / top_n` | 本地 bge-reranker 模型路径 + 候选数 |
| `langfuse.*` | 可观测（可选） |
| `ui.*` | db_path / 语言 / 主题 |
| `*_api_key` | 密钥（SecretStr，仅环境变量） |
| `docs_dir` | 文档目录 |

### 2.2 助手级（进 AssistantConfig，对应三档参数）

| AssistantConfig 字段 | 三档分级 | 对应现有 Settings 字段 |
|---|---|---|
| `generative_model` | 强建议 | `llm.primary`（+ `llm.fallback`） |
| `embedding_model` | 强建议 | `embedding.model` |
| `top_k` | 用户自滑 | `retrieval.top_k` |
| `chunk_size` | 用户自滑 | `retrieval.chunk_size` |
| `rerank_enabled` | 用户自滑 | （新增，现有无此开关） |
| `vector_store` | 用户自选 | （新增，当前仅 `"qdrant"`） |
| `chunk_overlap` | 不暴露 | `retrieval.chunk_overlap` |
| `temperature` | 不暴露 | `llm.temperature` |

**关键设计**：助手级字段存「**选哪个**」（如 `vector_store="qdrant"`、`generative_model="deepseek-flash"`），部署级字段存「**怎么连**」（如 `qdrant.path`、`deepseek_api_key`）。两者解耦。

---

## 3. AssistantConfig 数据模型（pydantic）

```python
# src/enterprise_kb/assistant.py
from pydantic import BaseModel

class AssistantConfig(BaseModel):
    """每助手一份的可调配置（三档参数）。默认值从全局 Settings 继承。"""

    # 强建议档（离散、证据清晰）
    generative_model: str = ""        # 空 = 用全局 llm.primary
    embedding_model: str = ""         # 空 = 用全局 embedding.model

    # 用户自滑档（成本/质量权衡）
    top_k: int = -1                   # -1 = 用全局 retrieval.top_k
    chunk_size: int = -1              # -1 = 用全局 retrieval.chunk_size
    rerank_enabled: bool | None = None  # None = 用全局行为

    # 用户自选档
    vector_store: str = "qdrant"      # 当前仅 "qdrant"

    # 不暴露档（默认值，通常不展示）
    chunk_overlap: int = -1           # -1 = 用全局 retrieval.chunk_overlap
    temperature: float = -1.0         # -1 = 用全局 llm.temperature
```

**约定**：用哨兵值（空字符串 / `-1` / `None`）表示「未覆盖，回退全局」，这样单条记录只存用户改过的字段，避免全量冗余。

---

## 4. 存储接口（复用 storage.py 的 sqlite3 模式）

沿用现有 `storage.py` 的写法（标准库 sqlite3 + dataclass/CRUD + 每操作独立建连）：

> **db 路径决策（实现时确定）**：不复用会话库 `chat.db`，也不新建独立 `assistant.db` 目录配置；而是**复用 `ui.db_path` 的目录 + 独立文件名 `assistant.db`**。理由：零 `config.py` 改动、保留 config-driven 的目录隔离、测试可用现有 `UI__DB_PATH` 环境变量隔离（与 `test_storage.py` 的 `tmp_db` fixture 一致）。

```python
# src/enterprise_kb/assistant.py（或独立 storage_assistant.py）

def _init(conn) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS assistants (
            id            TEXT PRIMARY KEY,     -- assistant_id (UUID)
            name          TEXT NOT NULL,
            template      TEXT,                 -- 模板名，自定义为 NULL
            created_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assistant_configs (
            assistant_id    TEXT PRIMARY KEY,
            config_json     TEXT NOT NULL,      -- AssistantConfig.model_dump_json()
            updated_at      TEXT NOT NULL,
            FOREIGN KEY (assistant_id) REFERENCES assistants(id) ON DELETE CASCADE
        );
    """)

def upsert_assistant_config(assistant_id: str, config: AssistantConfig) -> None: ...
def get_assistant_config(assistant_id: str) -> AssistantConfig | None: ...
```

**决策**：`assistant_configs` 存 `config_json`（整条 JSON），不拆成多列。理由：参数会随产品迭代增删，JSON 列避免频繁 `ALTER TABLE`。

---

## 5. 加载函数（桥接全局 → 助手级）

```python
# src/enterprise_kb/assistant.py
from enterprise_kb.config import get_settings

def load_assistant_config(assistant_id: str | None) -> AssistantConfig:
    """加载助手配置，未覆盖字段回退全局 Settings。

    assistant_id 为 None 时，返回「全默认」配置（等价于纯全局行为）。
    """
    cfg = AssistantConfig()
    if assistant_id:
        stored = get_assistant_config(assistant_id)
        if stored:
            cfg = stored
    return cfg  # 哨兵值字段由调用方 resolve 到全局
```

**resolve 逻辑**（调用方）：
```python
def resolve(cfg: AssistantConfig) -> ResolvedConfig:
    s = get_settings()
    return ResolvedConfig(
        generative_model = cfg.generative_model or s.llm.primary,
        embedding_model  = cfg.embedding_model  or s.embedding.model,
        top_k            = cfg.top_k if cfg.top_k > 0 else s.retrieval.top_k,
        chunk_size       = cfg.chunk_size if cfg.chunk_size > 0 else s.retrieval.chunk_size,
        chunk_overlap    = cfg.chunk_overlap if cfg.chunk_overlap > 0 else s.retrieval.chunk_overlap,
        temperature      = cfg.temperature if cfg.temperature >= 0 else s.llm.temperature,
        ...
    )
```

---

## 6. 迁移路径（三阶段，渐进式）

### Phase A（本次拆解范围）
新增 `assistant.py`（`AssistantConfig` + 存储 + `load_assistant_config`），**不改现有 61 处 `get_settings()`**。纯新增能力，零破坏。

### Phase B（接评估闭环时）
新模块 `evaluate.py` / `seed_questions.py` / `suggest.py` 直接调用 `load_assistant_config`，评估时把 `config_snapshot` 传给检索/生成函数。

### Phase C（后期，按需）
把核心函数加 `config` 参数，让它们真正读助手级配置。**但**——见 §7，这一步大部分已经不用做了。

---

## 7. 关键发现：核心函数已支持参数注入（大幅降低 Phase C 成本）

摸排现有代码后确认：

| 参数 | 现有注入能力 | Phase C 是否需要改 |
|---|---|---|
| `top_k` | ✅ `retrieve_hybrid(query, top_k=None)` 已支持 | **不用改**（直接传参） |
| `generative_model` | ✅ `generate_answer(query, contexts, model=None)` 已支持 | **不用改** |
| `chunk_size` | ❌ `load_and_split()` 读全局 `retrieval.chunk_size` | 需加 `chunk_size` 参数 |
| `embedding_model` | ❌ `get_embedding_model()` 读全局 + 全局 `_model` 缓存 | 需改（多模型缓存，较复杂，后置） |
| `rerank_enabled` | ❌ 无开关（当前靠「是否调用 rerank 函数」隐式决定） | 需加开关 |

**结论**：
- **MVP 最小闭环只调 `top_k`** → 核心函数已支持注入，**Phase C 几乎不用做**，`AssistantConfig` 的作用只是「持久化用户确认的参数 + 评估时作为快照传递」。
- `chunk_size` / `embedding_model` / `rerank_enabled` 的注入是**后续扩展**（尤其 embedding_model 涉及多模型缓存，最复杂，最后做）。

---

## 8. 实现记录（spec delta）

### 已完成
- [x] 新增 `src/enterprise_kb/assistant.py`：`AssistantConfig` + `ResolvedConfig` + `resolve` + `assistants`/`assistant_configs` 两张表 + `create_assistant`/`upsert_assistant_config`/`get_assistant_config`/`load_assistant_config`/`get_resolved_config`/`delete_assistant`
- [x] 单元测试 `tests/test_assistant.py`：**12 个测试全绿**（哨兵值回退、部分覆盖、边界值 temperature=0.0、CRUD 往返、upsert 覆盖、级联删除、不存在场景）
- [x] 未 commit（等爸爸猫自己来）

### 与设计的偏差（实现时确定）
1. **db 路径**：设计稿 §4 写「独立 eval.db」，实现改为「复用 `ui.db_path` 目录 + `assistant.db`」（见 §4 顶部决策说明）
2. **补充公开函数**：新增 `delete_assistant()`（与 `storage.delete_session` 对称，API 完整性 + 测试不用私有 `_connect`）、`get_resolved_config()`（加载 + resolve 一步到位）
3. **字段命名**：`ResolvedConfig` 字段与 `AssistantConfig` 完全对齐（仅哨兵值类型不同）

### 测试环境备注
- 项目 `.venv` 是空的，实际 venv 在 `/data/venvs/enterprise-kb`
- 跑测试需 `env -u http_proxy ... PYTHONPATH=src /data/venvs/enterprise-kb/bin/python -m pytest`（清 socks 代理，否则 litellm import 时联网取 cost map 报错 `Unknown scheme for proxy URL`）
