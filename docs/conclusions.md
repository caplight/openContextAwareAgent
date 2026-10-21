# Phase 2 结论固化（检索质量优化）

> 本文档是 Phase 2（混合检索 + Reranker + Graph-RAG）的**结论性总结**，沉淀所有可复用的洞察。
> 数据来源：`docs/evaluation/` 下各阶段结果文件。评测协议见 `docs/evaluation/README.md`。

---

## 一句话结论

**正确检索架构 = hybrid（BM25+dense）召回 top-20 → reranker（bge-reranker-v2-m3）精排 top-3**；
但**多跳问答的真正瓶颈在生成器，不在检索**——检索做到极致（gold_recall@3 0.94），通用 LLM 答对率也只有 0.58；
只有 Graph-RAG 图推理（给生成器跨段落推理结构）才能把答对率拉到 0.75。

---

## 1. 演进曲线（golden corpus 1991 段，50 条固定测试集，可公平对比）

> 注：faithfulness / context_precision 有 LLM judge 随机性（±0.03~0.05），gold_recall@3 是客观指标（零 LLM，稳定）。下表为最新一次 judge（含 answer_correctness）。

| 阶段 | answer_correctness | faithfulness | context_precision | gold_recall@3 |
|------|--------------------|--------------|-------------------|---------------|
| Phase 1 naive dense top-3 | 0.516 | 0.908 | 0.532 | 0.8000 |
| Phase 2a hybrid（BM25+dense+RRF）| 0.454 | 0.897 | 0.527 | 0.7500 |
| Phase 2b hybrid + reranker | **0.580** | **0.941** | **0.642** | **0.9400** |

**结论：**
1. **hybrid 单独用不升反降**——BM25 稀疏词匹配在长段落（580 字符）+ 语义相关但词面不同时引入噪声。
2. **reranker 在「检索质量」上确实是真赢家**——gold_recall@3 80→94（+14pp）、faithfulness 90→94、context_precision 53→64，三项全面大涨。
3. **但「检索质量」≠「答对率」**：answer_correctness 全程低位（0.45~0.58），即使 rerank 把 gold 段落捞进 top-3（gold_recall@3 0.94），通用 LLM 答对率也只有 0.58。**检索做对了，生成器答不对。**
4. **hybrid 的价值不在「直接输出 top-3」，而在「提供更全 top-20 候选池给 reranker」**。正确链路是「召回→精排」，不是 hybrid 直接出结果。

---

## 2. Graph-RAG（LightRAG）端到端（20 条 → 50 条扩样）

> 注：LLM judge 随机性 + 小样本，各指标有 ±0.1 波动，排序比绝对值可靠。

### 20 条（200 段候选池，前 20 条）

| 模式 | answer_correctness | faithfulness | context_precision | gold_recall |
|------|--------------------|--------------|-------------------|-------------|
| local | 0.6450 | 0.7167 | 0.4110 | 0.70 |
| global | 0.6917 | 0.8583 | 0.4306 | 0.75 |
| hybrid | **0.7933** | **0.9250** | 0.4029 | **0.80** |

### 50 条（492 段候选池，全 50 条，与 2a/2b 对齐）

| 模式 | answer_correctness | faithfulness | context_precision | gold_recall |
|------|--------------------|--------------|-------------------|-------------|
| local | 0.7529 | 0.8667 | 0.5196 | 0.80 |
| global | 0.7164 | 0.8283 | 0.5233 | 0.74 |
| hybrid | 0.7487 | **0.9000** | 0.4806 | 0.80 |

**结论（20 → 50 条修正）：**
1. **「hybrid 明显最优」被扩样推翻**：20 条时 hybrid answer_correctness 0.79 领先，50 条时三模式收敛到 0.72~0.75（差异 <0.04，噪声内）。**正是之前担心的「hybrid 0.78 领先需确认非噪声」——现在确认了，是抽样偏差。**
2. **稳定不变的结论**：
   - Graph-RAG 端到端 answer_correctness ~0.72~0.75，仍高于隔离检索 0.63（端到端图推理 > 隔离检索，这个结论仍成立）。
   - **hybrid 的 faithfulness 始终最高**（0.925→0.900），答案最忠于 context。
   - local / hybrid 的 gold_recall 都 0.80，略高于 global 0.74。
3. **mode 选择影响有限**：local/global/hybrid 对最终答对率（answer_correctness / gold_recall）影响不大，主要影响 faithfulness（hybrid 最好）。
4. **小样本教训**：20 条连排序都会翻车（hybrid 从「第一」变「并列」），50 条才基本稳；结论必须在大样本 + 大候选池上定。

### 2.1 gold_recall 交叉验证（答案层 0/1 客观指标，零 embedding）

新增 `gold_recall`（LLM 判「预测答案是否答对 gold answer」，0/1）交叉验证「简洁版 faithfulness 低是不是假象」：

- **50 条下 gold_recall local 0.80 = hybrid 0.80 > global 0.74**，与 answer_correctness（三模式已收敛）排序不完全一致，说明两个指标关注点不同。
- **faithfulness 简洁版下降是评测口径问题**：简洁答案 statement 少（含「I don't have enough information」这类功能性语句，在 context 找不到对应），faithfulness 的 NLI 判「statement 是否被 context 支持」时被系统性压低；但 gold_recall 0.74~0.80 说明**实际答对率不低**。
- 结论：faithfulness 衡量「答案是否忠于 context」（precise 方向），gold_recall 衡量「答没答对 gold」（recall 方向），两者在不同 prompt 风格下有张力，需结合看。

### 2.2 三条链路 answer_correctness 终极对比（全部 50 条，核心发现）

把「检索质量」和「答对率」分开看，三条链路生成器都是 deepseek-flash，唯一变量是「喂给生成器的上下文结构」：

| 链路 | 生成方式 | 候选池 | answer_correctness | faithfulness | context_precision |
|------|---------|--------|--------------------|--------------|-------------------|
| 2b 检索链路（hybrid_rerank） | 通用 LLM（rerank top-3） | 1991 段 | **0.580** | 0.941 | 0.642 |
| 隔离检索（LightRAG hybrid） | 通用 LLM（LightRAG chunks） | 492 段 | **0.634** | **0.987** | 0.455 |
| 端到端图推理（hybrid） | 图推理（实体链+社区） | 492 段 | **0.749** ⬆️ | 0.900 | 0.481 |

**核心结论（重要）：多跳问答的瓶颈在生成器，不在检索。**

1. **检索做得再好，通用 LLM 也答不对**：2b 检索质量最高（gold_recall@3 0.94，context_precision 0.64），但通用 LLM 拿到 rerank top-3，答对率只有 0.58。**检索做对了，生成器答不对。**
2. **上下文结构决定答对率**：同样 deepseek-flash，喂 `rerank top-3 段落` → 0.58，喂 `LightRAG 多 chunk` → 0.63，喂 `图推理实体关系链` → 0.75（+17pp）。
3. **Graph-RAG 的价值不在检索**（context_precision 0.48 反而低于 2b 的 0.64），而在于**给生成器提供跨段落的推理结构**（实体关系链 + 社区摘要），让 LLM 能跨段推理多跳问题。
4. **代价**：图推理的 faithfulness 0.90 低于隔离检索 0.99（简洁 prompt 的「I don't have enough information」等功能性语句被 NLI 压低），但 gold_recall 0.80 说明实际答对率不低。

---

## 3. 三次归因反转（重要教训：别急着下「图不行」的结论）

Graph-RAG 端到端最初 answer_correctness 只有 0.42（vs 隔离检索 0.63），连续两轮归因都错了：

| 轮次 | 归因 | 结论 |
|------|------|------|
| 第 1 轮 | 图太稀疏，第二跳关系边缺失 | ❌ 错（图里其实有边） |
| 第 2 轮 | 图推理断链、只答第一跳 | ❌ 错（完整答案其实答对了第二跳） |
| 第 3 轮 | 默认 prompt 逼 LLM 写啰嗦长答案 + factuality 指标偏差 | ✅ 对 |

**真根因**：LightRAG 默认 `rag_response` prompt 写死「comprehensive + Markdown + References + 多段落」，逼 LLM 输出啰嗦长答案；而 `answer_correctness` 的 factuality = 被 gold 支持的 statement ÷ 总 statement，啰嗦答案 statement 多 → 大量 FP 稀释分数。

**修复**：自定义简洁 system_prompt（只给最终答案，无 Markdown/References）+ `enable_llm_cache=False`（否则新 prompt 被旧缓存 hash 吃掉）。修完后 answer_correctness 0.42→0.78。

**指标张力（诚实记录）**：
- `answer_correctness` 偏好**简洁**答案（statement 少好命中）
- `faithfulness` 偏好**详细**答案（statement 多更易被 context 支持）
- 简洁版 faithfulness 降（0.72~0.85 vs 啰嗦版 0.92~0.98）是评测口径问题，非系统变差。

---

## 4. 技术踩坑清单（可复用）

### 评测工程
1. **候选池大小决定结论方向**：早期用「每条 10 段 gold context」当候选池，严重低估 reranker 价值（hybrid 测出 58%>51.83% 是假象）。真实 1991 段候选池下 hybrid 单独用反降。**结论必须在大候选池上验证。**
2. **embedding 慢的根因是 swap 抖动**：残留 demo 服务（FastAPI 8000 + Streamlit 8501）各加载一份 bge-m3 占 ~1.9GB swap，不是 CPU 慢。杀掉残留 + 释放 swap 后恢复正常。
3. **4 核 VM 上 batch_size=16 最优**（0.48s/段），batch 32 触发 swap 反而变慢。
4. **reranker cross-encoder CPU 很慢**：每条 query 对 20 候选打分 ~17-27s，上全量前需批量化。

### RAGAS 版本连环坑
1. ragas 0.4.3 需降级 langchain 到 0.3.x（否则 vertexai ModuleNotFoundError）
2. 新 `ragas.metrics.collections.AnswerCorrectness` 无 `single_turn_score`、默认 weights 含 semantic similarity 需 embeddings；旧 `ragas.metrics.AnswerCorrectness`（deprecated）有 `single_turn_score` 返回 float，用 `weights=[1.0, 0.0]` 纯 factual
3. `single_turn_ascore` 是异步，同步用 `single_turn_score`，参数是 `SingleTurnSample` 对象

### LightRAG API 坑
1. `insert` 前必须 `await rag.initialize_storages()`（否则 PipelineNotInitializedError）
2. `enable_rerank` 默认 True，评测要显式 `enable_rerank=False`
3. `QueryParam.mode` 默认是 `mix` 不是 `hybrid`
4. `enable_llm_cache=False` 必须显式设（否则换 system_prompt 被旧缓存吃掉）
5. 生成先试 claude（无 key 失败）再 fallback deepseek 每条多 ~13s，评测里显式传 `model="deepseek/deepseek-flash"` 跳过

### 环境/网络
1. **代理坑**：`unset ALL_PROXY`（socks 不被 httpx 支持）但保留 `HTTP_PROXY/HTTPS_PROXY`（http 代理供 HF 下载）
2. venv 是 uv 管理，`pip install` 报 externally-managed → 用 `uv pip install`

---

## 5. 待验证 / 未决事项

- [x] **扩全 50 条** ✅ 已做：hybrid 的「明显最优」被推翻——三模式 answer_correctness 收敛到 0.72~0.75（20 条的 0.79 领先是抽样偏差），但 hybrid 的 faithfulness 仍最高（0.90）。见 §2。
- [x] **跑 gold-recall 交叉验证** ✅ 已做：hybrid gold_recall 0.80（> global 0.75 > local 0.70），与 answer_correctness 一致；确认简洁版 faithfulness 低是评测口径问题，实际答对率不低（见 §2.1）
- [x] **reranker 批量化提速** ✅ 已做：新增 `rerank_batch`（合并所有 query-candidate pairs 一次 predict），真实段落下 127s→66s，**提速 1.91x**；batch_size 默认 32 最优（=100 反而变慢）
- [x] **补 2b 检索链路 answer_correctness** ✅ 已做：2b 检索质量最高（gold_recall@3 0.94）但 answer_correctness 仅 0.58，证明「检索≠答对率」（见 §2.2）
- [x] **隔离检索扩 50 条** ✅ 已做：local/global/hybrid = 0.657/0.613/0.634，对比端到端图推理 0.75，证明「图推理 0.75 > 隔离检索 0.63 > 纯检索链路 0.58」（见 §2.2）
- [ ] 上全量 1991 段做 Graph-RAG **图推理**严格对比（当前图推理只在 492 段候选池，1991 段下是否保持 0.75 优势——**待证，非保证**）
- [ ] 权重超参数（BM25 vs dense）需在真实 K8s/AWS 物料 + 真实 query 上定标，golden corpus 是 Wikipedia 代理，结论未必可迁移
