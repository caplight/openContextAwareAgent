# DevOps 助手（ReAct agent）

Phase 3 的「查得准、讲得清」能力：一个 ReAct agent，用工具池（查集群 + 查文档）多步取证，回答「这个故障是什么、为什么、该怎么修」。

## 定位

- **被动响应**：用户提问 → agent 取证 → 给结论。不主动监控、不主动修复、不执行任何变更操作（只读）。
- **能力边界**：查状态、查事件、查日志、查文档、做 root cause 分析。**不**做「判真故障后自动修复」「观察窗口/断路器判定」——这些属于后续阶段（见 memory 归档）。

## 架构

```
用户问题
   │
   ▼
┌─────────────────────────────────────┐
│  ReAct agent（create_react_agent）  │
│  模型：ChatLiteLLM（deepseek-flash） │
│  循环：思考 → 选工具 → 执行 → 再思考 │
└─────────────────────────────────────┘
   │ 自主决定调用哪个工具、按什么顺序
   ▼
   工具池（6 个）
   ├── k8s_get / k8s_describe / k8s_logs / k8s_events  ← 查集群（kubectl）
   ├── kb_search                                        ← 查文档（向量库）
   └── web_search                                       ← 联网搜索（Brave，补充本地不足）
```

## 工具清单

| tool | 入参 | 回答什么 |
|---|---|---|
| `k8s_get` | kind, name, namespace? | 「现在是什么状态」（phase/READY/RESTARTS） |
| `k8s_describe` | kind, name, namespace? | 「为什么」——事件流、探针失败、调度失败原因 |
| `k8s_logs` | pod, container?, tail, previous? | 容器日志（`--previous` 取崩溃前输出） |
| `k8s_events` | namespace?, involved_name? | 事件时间线（重建故障过程） |
| `kb_search` | query, top_k? | 知识库文档片段（最佳实践 / 怎么做） |
| `web_search` | query, top_k? | 联网搜索（本地知识库未覆盖时补充，返回标题+链接+摘要） |

## 用法

```bash
# 1. 注入 key（仅环境变量，不落盘）
export DEEPSEEK_API_KEY=sk-xxx

# 2. 提问（agent 自主决定查集群还是查文档）
uv run kb agent "payment-svc 一直重启为什么"
uv run kb agent "这个 OOMKilled 跟文档里的 limits 最佳实践对不对得上"
```

也可以程序化调用：

```python
from enterprise_kb.agent import ask

result = ask("fake-node-2 为什么 NotReady")
print(result["answer"])          # 最终回答
# result["messages"] 是完整轨迹（含中间 tool 调用，供调试/可观测）
```

## 设计要点

1. **薄封装**：4 个 k8s 工具只做「拼 kubectl 命令 → 返回原始文本」，不做状态解析，让 agent 自己解读（工具保持单一职责，ReAct 模式）。
2. **方案 A（检索与生成分离）**：`kb_search` 只返回片段，不生成答案；最终结论由 agent 综合所有证据后产出——这样 agent 能把「集群现状」和「文档知识」两条线合起来判断。
3. **复用现有链路**：`kb_search` 直接调 `retrieve_hybrid_candidates` + `rerank`，不重复造轮子；模型走 `config.llm.primary`，key 走 `_setup_keys()` 注入。
4. **输出截断**：describe/logs 超长时截断到 8000 字符（保留首尾），防止撑爆上下文。
5. **本地优先、联网补充**：`web_search` 是 `kb_search` 的补充——本地知识库检索不到或覆盖不足时，agent 才转去联网搜索（system prompt 里约束了优先级）；联网结果要求标注来源链接。

## 已知限制

- **首次调用慢**：`kb_search` 首次会加载 bge-m3（~4s）+ reranker（~30s，CPU），后续缓存模型，但 cross-encoder 每次推理仍约 10s。
- **需要建好索引**：`kb_search` 依赖 `kb ingest` 已跑（否则返回空提示）。
- **需要 API key**：`DEEPSEEK_API_KEY`（生成）+ `BRAVE_API_KEY`（联网搜索）只走环境变量注入（或 `.env`，已被 gitignore）。

## 踩坑记录

1. **`create_react_agent` 的 system prompt 参数**：本版本 langgraph 用 `prompt=`（旧版是 `state_modifier=`），传错会 TypeError。
2. **`@tool` 装饰器的调用方式**：生成的 tool 要用 `.invoke({"arg": ...})`，不能关键字直接调（`tool(arg=...)` 会 TypeError）。
3. **代理干扰**：运行时 `unset ALL_PROXY`（socks 代理会让 litellm import 报 `ValueError: Unknown scheme for proxy URL`）。

## MCP 封装（已完成）

工具逻辑已抽到框架无关的 `enterprise_kb.core`（单一真相源），并提供两个适配器：

```
enterprise_kb.core（框架无关，零 agent 框架依赖）
  ├─ core/k8s.py    ：kubectl 薄封装 + 4 个查询函数（k8s_get/describe/logs/events）
  ├─ core/search.py ：kb_search 检索（复用 retrieve + rerank）
  └─ core/web.py    ：web_search 联网搜索（Brave Search API）
        ↓ 适配器（复用同一份 core，逻辑只有一份实现）
  ├─ tools.py        → LangChain StructuredTool（ReAct agent 用）
  └─ mcp_server.py   → MCP 协议（跨框架客户端用）
```

- **LangChain 适配器**（`tools.py`）：把 core 函数包装成 `StructuredTool`（自动继承签名 + docstring），供 ReAct agent 使用，行为与重构前一致。
- **MCP server**（`mcp_server.py`）：用 `MCPServer`（mcp 2.x，原 `FastMCP` 已改名）把同一份 core 函数暴露成标准 MCP 协议，任何 MCP 客户端（Claude Desktop / Cursor / 其他 agent 框架）都能调用，无需依赖 LangChain。

运行 MCP server：

```bash
# stdio（供 MCP 客户端 spawn）
uv run kb mcp

# SSE（供远程客户端，0.0.0.0:8000）
uv run kb mcp --transport sse --port 8000
```

MCP 依赖是可选依赖，安装：`uv sync --extra mcp`（或 `uv pip install mcp`）。

## 后续

- **Skills 封装**：把工具再包装成 OpenClaw 风格的 skill 声明（SKILL.md），让 OpenClaw agent 也能直接调用（已记入 memory 待办）。
- **「主动操作」「观察窗口/断路器判定」**：后续阶段，当前不落地。
