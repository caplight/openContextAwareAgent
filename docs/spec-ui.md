# Kubernetes DevOps 助手 — Web UI 规格（Spec）

> 状态：已定稿 v1.0
> 开发模式：spec-driven + config-driven + test-driven
> 日期：2026-11-08

---

## 1. 目标与非目标

### 目标
用 React + Vite + Tailwind 替换现有 Streamlit 前端，提供一个现代化的 DevOps 助手聊天界面，
核心差异化是**工具调用可视化**（让用户看清 agent 的 k8s 取证链）+ **流式输出**。

### 非目标（本次不做，二期再议）
- RAG 可观测 Dashboard（现有 `dashboard.py` 暂留 Streamlit）
- 多用户登录 / 权限体系
- 人机审批（Human-in-the-loop，当前 agent 只读不改，无写操作工具）
- 模型切换、消息搜索、快捷键

---

## 2. 功能需求

### P0（MVP 核心）

| # | 功能 | 验收标准 |
|---|------|---------|
| F1 | **流式输出** | 回答 token 逐字渲染；发送即出现 typing 指示器；首 token ~1s 内 |
| F2 | **工具调用可视化** | 每次 tool call 渲染为独立步骤卡片，含：工具名、入参（可折叠）、状态（进行中/成功/失败）、耗时；返回结果可折叠展开 |
| F3 | **Reasoning 思考块** | agent 每次行动前的推理过程，以折叠块展示（默认折叠，可展开） |
| F4 | **Markdown 渲染** | 表格、代码块（高亮）、列表、链接正常渲染 |
| F5 | **多轮对话 + 会话历史** | 上下文连续；历史消息可回看 |
| F6 | **停止生成** | 生成中可点击停止，立即中断流式 |

### P1（体验提升）

| # | 功能 | 验收标准 |
|---|------|---------|
| F7 | **消息操作** | 复制（含 Markdown 源码）/ 重新生成 / 编辑上一条并重新发送 |
| F8 | **会话管理** | 左侧栏：新建会话、重命名、删除、切换；会话持久化（刷新不丢） |
| F9 | **引用来源** | `kb_search` 命中的文档片段 + `web_search` 的链接，回答末尾/步骤内可点击溯源 |
| F10 | **暗色/亮色主题** | 切换主题；默认暗色（DevOps 场景） |
| F11 | **中英切换** | 沿用现有 locales 字典；默认英文 |

---

## 3. 技术架构

```
┌─────────────┐   SSE (EventSource)   ┌──────────────────┐
│  React + Vite │ ◄────────────────── │  FastAPI          │
│  + Tailwind   │                      │  /api/chat (SSE)  │
│  (静态托管)   │                      │  /api/sessions    │
└─────────────┘                      └────────┬─────────┘
                                              │
                                     LangGraph astream_events
                                              │
                              ┌───────────────┴───────────────┐
                              │  create_react_agent           │
                              │  (ChatLiteLLM + ALL_TOOLS)     │
                              └───────────────────────────────┘
```

- **后端**：FastAPI，把 `agent.ask()` 升级为流式（LangGraph `astream_events`），
  产出 token 流 + `on_tool_start/end` + reasoning 事件。
- **前端**：React + Vite + Tailwind；`EventSource` 接 SSE；停止生成用独立 `POST /api/chat/{run_id}/cancel`。
- **部署**：前端 `vite build` 产物由 FastAPI 托管（单端口），cloudflared 继续穿透。

---

## 4. 数据模型

### Session（会话）
```
id: UUID
title: str            # 默认取首条消息前 N 字，可重命名
created_at: datetime
updated_at: datetime
```

### Message（消息）
```
id: UUID
session_id: UUID
role: "user" | "assistant"
content: str          # assistant 的最终 Markdown 文本
tool_trace: list[ToolCall]   # 该轮的工具调用轨迹（含 reasoning）
created_at: datetime
```

### ToolCall（工具调用，内嵌在 Message 内，不单独建表）
```
name: str             # k8s_get / kb_search / web_search ...
args: dict
output: str           # 原始返回（供展开查看）
status: "running" | "success" | "error"
duration_ms: int
```

### Source（引用来源，P1 / F9）
```
title: str
url: str | None       # web_search 有；kb_search 无
snippet: str
```

> 持久化：SQLite（后端，单文件 `data/chat.db`）。单用户（无登录），会话用 UUID 隔离，API 预留多用户。

---

## 5. API 契约

### 5.1 流式聊天 `POST /api/chat`（SSE）

请求：
```json
{ "session_id": "uuid|null", "message": "我的 pod 为什么重启？" }
```

响应事件流（`text/event-stream`）：

| event | data 字段 | 说明 |
|-------|----------|------|
| `meta` | `{session_id, model}` | 会话/模型元信息 |
| `reasoning_start` | `{step}` | 开始一段思考 |
| `reasoning_delta` | `{delta}` | 思考内容增量 |
| `reasoning_end` | `{}` | 思考结束 |
| `tool_start` | `{id, name, args}` | 工具开始调用 |
| `tool_end` | `{id, name, output, status, duration_ms}` | 工具结束 |
| `text_delta` | `{delta}` | 回答文本增量 |
| `citations` | `{sources:[{title,url,snippet}]}` | 引用来源（F9） |
| `done` | `{answer, usage:{prompt_tokens,completion_tokens}}` | 完成 |
| `error` | `{message}` | 出错 |

### 5.2 会话管理（REST）

```
GET    /api/sessions              # 列出会话（按 updated_at 倒序）
POST   /api/sessions              # 新建会话
GET    /api/sessions/{id}         # 获取会话 + 消息
PATCH  /api/sessions/{id}         # 重命名
DELETE /api/sessions/{id}         # 删除
```

### 5.3 停止生成

```
POST /api/chat/{run_id}/cancel    # 中断某次流式运行
```

---

## 6. 前端组件结构

```
src/
  main.tsx
  App.tsx
  i18n.ts                # 中英字典（从 locales.py 迁移）
  api/client.ts          # SSE + REST 封装
  components/
    ChatWindow.tsx       # 消息列表 + 滚动
    MessageBubble.tsx    # 单条消息（user/assistant）
    ToolCallCard.tsx     # 工具调用步骤卡片（F2）
    ReasoningBlock.tsx   # 思考折叠块（F3）
    Markdown.tsx         # Markdown 渲染 + 代码高亮（F4）
    Composer.tsx         # 输入框 + 发送/停止（F1/F6）
    CitationList.tsx     # 引用来源（F9）
    SessionSidebar.tsx   # 会话管理（F8）
    ThemeToggle.tsx      # 暗色/亮色（F10）
    LangToggle.tsx       # 中英切换（F11）
```

---

## 7. 配置项（config-driven）

在 `config.py` 新增 `UIConfig`，环境变量 `UI__` 前缀：

```python
class UIConfig(BaseModel):
    default_lang: str = "en"        # en | zh
    default_theme: str = "dark"     # dark | light
    sse_heartbeat_sec: int = 15     # SSE 心跳间隔
    session_ttl_days: int = 30      # 会话保留天数
```

---

## 8. 测试策略（test-driven）

- **后端（pytest）**：
  - `test_agent_stream.py`：`astream_events` 事件序列正确（含 tool_start/end、reasoning、text_delta）
  - `test_api.py`：SSE 端点 + 会话 CRUD（用 httpx / TestClient）
  - `test_core_structured.py`：`kb_search`/`web_search` 结构化返回（F9 引入后）
- **前端（vitest + React Testing Library）**：
  - `ToolCallCard` 渲染各状态、`Markdown` 渲染、`Composer` 发送/停止
  - SSE 客户端解析（mock EventSource）

---

## 9. 决策记录（已对齐，2026-11-08）

| # | 决策 | 结论 |
|---|------|------|
| Q1 | 会话持久化 | **SQLite**（后端单文件 `data/chat.db`） |
| Q2 | 引用来源深度 | **方案 B（结构化）**：改 `kb_search`/`web_search` 返回结构化元数据，回答里出可点击引用卡片 |
| Q3 | 单用户/多用户 | **单用户 demo（无登录）**，UUID 隔离，API 预留多用户 |
| Q4 | 默认语言 | **英文**（中文可切） |
| Q5 | Reasoning 数据源 | 实现时验证 deepseek `reasoning_content` 可否独立流式；拿不到则 F3 降级为仅工具步骤 |

### Q2 结构化引用 — 技术方案（content_and_artifact）

LangChain tool 支持 `response_format="content_and_artifact"`：工具函数返回
`(content, artifact)` 元组——`content` 是给 LLM 的纯文本，`artifact` 是任意结构化数据
（引用列表）。`artifact` 会随 `on_tool_end` 事件的 `ToolMessage.artifact` 字段流出，前端解析。

改动范围：
1. `core/search.py` / `core/web.py`：新增结构化返回（`SearchResult` dataclass，含 `hits` + `to_text()`）。
2. `tools.py`：`kb_search` / `web_search` 改用 `content_and_artifact`，`content`=文本、`artifact`=sources 列表。
3. `agent` 流式层：`on_tool_end` 解析 `artifact` → 产出 `citations` SSE 事件。
4. MCP server：MCP tool 仍返回文本（结构化引用本期仅覆盖 Web UI 路径）。

---

## 10. 里程碑

- **M1**：后端流式（agent → astream_events → SSE）+ 会话持久化
- **M2**：前端骨架（Vite + Tailwind + 布局 + 双语 + 主题）
- **M3**：流式聊天 + 工具调用可视化 + reasoning + Markdown
- **M4**：会话管理 + 消息操作 + 引用来源 + 停止生成
- **M5**：测试补全 + cloudflared 部署验证
