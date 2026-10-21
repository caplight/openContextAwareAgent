# KPI 定义（RAG demo 的核心衡量指标）

> 本项目要证明的三件事：**检索质量硬、成本/延迟可控、全程可观测**。
> 每个 KPI 都要「可测量、可复现、可对比」，拒绝拍脑袋的定性描述。

## 总览

| # | KPI | 目标值 | 测量方法 | 当前状态 |
|---|-----|--------|----------|----------|
| 1 | 答案准确率 | ≥ 90% | RAGAS（faithfulness + answer relevancy） | ✅ faithfulness 96.92%（hybrid+rerank，golden corpus）/ context_precision 57.33% |
| 2 | 单次查询 LLM 成本 | < $0.01 | LiteLLM cost map（token × 单价） | ✅ 实测 $0.00056/次（远低于 $0.01） |
| 3 | P95 端到端延迟 | < 3s | Langfuse trace 计时 | ❌ 热查询 P95 26s（rerank CPU 瓶颈）；待 GPU/优化 |
| 4 | Graph-RAG 相对提升 | +15~20% | naive vs Graph-RAG 同集对比 | ✅ 多跳 answer_correctness 0.78（hybrid 简洁版），见 docs/conclusions.md |

## 1. 答案准确率（≥ 90%）

- **定义**：RAG 系统给出的答案与 ground-truth 的一致性。
- **测量**：RAGAS 在 HotpotQA（distractor 子集）上算两个核心指标：
  - `faithfulness`：答案是否忠于检索到的上下文（不幻觉）
  - `answer_relevancy`：答案是否切题
  - `context_precision`：检索到的上下文是否精准
- **为什么用 HotpotQA**：有 ground truth（客观可比）；demo 展示用 K8s/AWS 文档（定性）。两者职责分离。
- **对标**：naive RAG 在 HotpotQA 上的公开基线约 60~75%，本项目目标是把它做到 90%。

## 2. 单次查询 LLM 成本（< $0.01）

- **定义**：一次完整 RAG 查询（检索 + 生成）里，LLM 推理的 token 成本。
- **测量**：`LLMResult.prompt_tokens` + `completion_tokens` × 模型单价（LiteLLM cost map）。
- **现状**：DeepSeek `deepseek-flash` 实测 prompt=302 / completion=602 tokens，成本远低于 $0.01。
- **Phase 4 完成**：`LLMResult` 加 `input_cost`/`output_cost`（litellm cost map 按 token × 单价拆算），`generate` span 回填 `cost_details`（input/output/total），Langfuse `totalCost` 与 dashboard「累计成本」有真实数字。
- **实测**：热查询 10 次平均单次成本 **$0.00056**（deepseek-flash，单价 input $0.3/M + output $1.2/M），远低于 KPI 目标 $0.01。
- **设计支撑**：LLM 分层（Haiku 5.5 主力 + DeepSeek Flash 备选），复杂查询才升级模型，控制边际成本。

## 3. P95 端到端延迟（< 3s）

- **定义**：从用户提问到返回答案的端到端耗时，取 P95 分位（排除偶发抖动）。
- **测量**：Langfuse trace 记录每个 span（retrieve / rerank / generate）耗时，`dashboard.py` 直接展示三段延迟分解。
- **Phase 4 实测（冷启动，单次进程加载模型）**：总 36.5s，其中 retrieve 4.84s / rerank 27.97s / generate 3.68s。冷启动大头是 reranker 首次加载（bge-reranker-v2-m3 2.2G）。
- **Phase 4 实测（热查询，N=10）**：P95 26.0s / mean 24.5s，三段分解 retrieve ~2.3s / rerank ~20.5s / generate ~2.2s。**瓶颈是 rerank**（cross-encoder 在 CPU 上对 ~36 候选打分 ~20s）。
- **结论**：CPU 无 GPU 下，rerank 是延迟最大头；达标（<3s）需 GPU（cross-encoder 降到几十 ms）或减少 rerank 候选数 / 换轻量 reranker。
- **现实约束**：当前环境无 GPU，bge-m3 走 CPU（embedding 单次 ~2s）。GPU（WSL2 / 4060 Ti）可降到几十 ms。
- **注**：CPU 环境下的延迟是「下限验证」，真正对标在 GPU 环境做。

## 4. Graph-RAG 相对提升（+15~20%）

- **定义**：Graph-RAG（Phase 2 接入，LightRAG）相对 naive RAG，在相同评测集上的准确率提升。
- **测量**：naive baseline 分数 vs Graph-RAG 分数，同集对比。
- **这是本项目最有说服力的增量**：证明「加了知识图谱/实体关系后，多跳推理类问题显著变好」。

---

## 测量记录存放

每次跑分结果落盘到 `docs/evaluation/`，命名 `phase{N}-{名称}.md`，含：
- 评测集 + 样本量
- 每个指标分数
- 与上一版对比（delta）
- 环境备注（CPU/GPU、模型、chunk 参数）

这样 metrics 结果可追溯、可复现，面试时能直接拿出「从 baseline 到优化后的完整演进曲线」。
