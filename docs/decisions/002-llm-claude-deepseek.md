# ADR-002：LLM 选 Claude Haiku 5.5 主力 + DeepSeek 备选

- **状态**：已采纳（定稿）
- **日期**：2026-10

## 背景（Context）

生成答案的 LLM 要满足：
- 单次查询成本 < $0.01（KPI #2）
- 质量够支撑 RAG 生成（引用准确、不幻觉）
- 用户在中国，支付用中国 Visa 卡（先不配 Claude 计费）

## 决策（Decision）

**分层路由**：
- 主力：`claude-haiku-5-5`（Anthropic，质量优先）
- 备选：`deepseek/deepseek-flash`（DeepSeek，便宜 + 国内直连）

通过 LiteLLM 封装，primary 失败或未配 key 时自动 fallback。

## 理由（Rationale）

1. **Haiku 5.5** 是 Anthropic 的速度/成本档，质量和价格平衡好（官方 docs 核实）
2. **DeepSeek Flash** 便宜且国内直连，当前阶段（未配 Anthropic key）是实际主力
3. 分层设计保证：演示时哪怕没配 Claude，也能跑（fallback 已验证）

## 后果（Consequences）

- 正面：成本可控、降级健壮
- 负面：两套 API key 管理；fallback 时质量略降（可接受）
- 配套：`LLMResult` 带 token 用量，为成本 KPI 提供数据
