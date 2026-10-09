# 技术选型横向对比

> 日期：2026-10-09
> 方法：需求先行 → 拉 3-4 个候选框架 → 横向对比 → 拍板

---

## 0. 选型锚点（先明确"要解决什么问题"）

### 技术需求（由 KPI 反推）
1. **检索质量**：混合检索（BM25 + 向量）+ rerank + Graph-RAG（护城河）
2. **成本可控**：模型路由、降级、统一接口层、成本可追踪到环节
3. **延迟可控**：本地部署、低延迟检索（<200ms）
4. **可观测**：100% trace、成本/延迟可归因
5. **单机可跑可录屏**：Docker Compose 一键起，demo 场景无网络依赖

### 用户需求（爸爸猫作为求职者）
1. **技术栈对齐 JD 加分项**：真实 JD 点名 n8n / Dify / LangGraph / MCP / RAG
2. **自托管优先**：0 成本、可录屏、面试现场可离线 demo
3. **学习曲线合理**：已有 LangChain / LangGraph / Pinecone / Neo4j 经验
4. **差异化**：Graph-RAG 是别人没有的护城河

---

## 1. 向量数据库

| 维度 | Qdrant | Weaviate | Milvus | Pinecone（托管） |
|---|---|---|---|---|
| 部署 | 自托管 Docker / 单机极简 | 自托管（较重） | 自托管（最重，需 etcd/MinIO） | 纯托管（SaaS） |
| 混合检索 | ✅ 原生 BM25+向量（sparse+dense） | ✅ 内置（但封装度高） | 需自行拼装 | ❌ 仅向量（需外接 BM25） |
| 过滤能力 | ✅ 最强（payload 过滤） | 中 | 中 | 中 |
| 性能/规模 | 中等规模最优性价比 | 中 | 亿级向量最强 | 10M 内省心 |
| 成本 | 免费自托管 | 免费自托管 | 免费自托管 | 按量付费（有免费 tier） |
| 维护 | 低 | 中 | 高 | 零 |

**结论：Qdrant ✅** — 本地自托管 0 成本、原生混合检索（省一个 BM25 组件）、过滤最强、单机 Docker 即可跑。Pinecone 托管爽但 demo 场景没必要 + 录屏要联网。

---

## 2. Embedding 模型

> 候选：bge-m3 / text-embedding-3-small / text-embedding-3-large / jina-embeddings-v4 / Qwen3-Embedding

| 维度 | bge-m3 | text-embedding-3-small | text-embedding-3-large | jina-v4 | Qwen3-Embedding |
|---|---|---|---|---|---|
| 检索质量(MTEB/MIRACL) | 强（MIRACL 多语言 SOTA） | 中（~62） | 强（~65） | 强 | 强（sub-1B 里 SOTA） |
| 多语言(中英) | ✅ 原生多语言 | ✅ | ✅ | ✅ | ✅ 中文最强 |
| **混合检索能力** | ✅ **dense + sparse + multi-vector 三合一** | ❌ 仅 dense | ❌ 仅 dense | 🟡 dense + multi-vector（**无 sparse**） | 🟡 仅 dense |
| 部署 | ✅ 本地 MIT | ❌ API 联网 | ❌ API 联网 | ✅ 本地(Apache2) | ✅ 本地 |
| 成本 | 0（本地推理） | 按 token | 按 token | 0 | 0 |
| 长文本 | 8K+ 轻微退化 | 稳定 | 稳定 | 稳定 | 稳定 |

**关键澄清（jina v3 vs v4）**：
- jina v4 的「混合」= **dense(2048维) + multi-vector（ColBERT 式 late-interaction）**，基于 Qwen2.5-VL-3B，主打多模态（文本+图片+视觉文档）
- 但它**不支持 sparse/lexical（词法检索）**——没有 BM25 式稀疏向量
- 而 **bge-m3 是 dense + sparse + multi-vector 三合一**，其中 sparse 正是能替代 BM25 的词法检索
- Qdrant 的原生混合检索（dense 向量 + sparse 向量）需要 embedding 模型输出 sparse 向量 → **只有 bge-m3 能单一模型同时给 dense + sparse**

**结论：bge-m3 ✅**（2026-10-09 定稿）
- 杀手锏：**三合一（dense+sparse+multi-vector）**，和 Qdrant 原生混合检索绝配，省掉额外 BM25 组件
- 本地 MIT 免费 + 离线录屏 + 多语言（demo 文档中英混合）
- 8K 退化短板对我们无所谓（chunk 才 512 tokens）

---

## 3. 模型路由层（LLM Gateway）

> 候选：LiteLLM / OpenRouter / Portkey / 自建精简

| 维度 | LiteLLM | OpenRouter | Portkey | 自建精简 |
|---|---|---|---|---|
| **① 成本（markup/订阅）** | ✅ 0 markup，直连厂商 | ❌ 有抽成（~5%） | ❌ 订阅费 + 按量 | ✅ 0（但开发成本高） |
| **② 降级/容灾（fallback/retry）** | ✅ 内置 | ✅ 简单 | ✅ 强 | ❌ 全自己写 |
| **③ 成本追踪/预算上限** | ✅ 原生 per-request + budget | ✅ 聚合 | ✅ 强 | ❌ 自己埋 |
| **④ 自托管/数据主权** | ✅ 完全自托管（MIT） | ❌ SaaS | ❌/部分 | ✅ |
| **⑤ 模型覆盖 + 切换灵活性** | ✅ 100+ 统一 OpenAI 接口 | ✅ 极广 | ✅ 广 | ❌ 自己适配 |

**结论：LiteLLM ✅**（2026-10-09 定稿）—— 五维全中，见 BLUEPRINT。

---

## 4. RAG/Agent 编排框架

| 维度 | LangGraph | LlamaIndex | Haystack | 自建纯 FastAPI |
|---|---|---|---|---|
| RAG 编排 | ✅ 强（图状态机） | ✅ 强（RAG 全家桶） | ✅ 强（pipeline） | 自己写 |
| Agent 能力 | ✅ 最强（状态图、可控性） | 中 | 中 | 自己写 |
| 可观测集成 | ✅ Langfuse/LangSmith 一等公民 | ✅ | ✅ | 自己埋 |
| 学习曲线 | 低（已有经验） | 低 | 中 | 中 |
| JD 对齐 | ✅ JD 点名 LangGraph | 未点名 | 未点名 | 无 |

**结论：LangGraph ✅** — 爸爸猫已有经验 + 真实 JD 明确点名 LangGraph + 状态图可控性最适合做「RAG + 智能路由 + Agent」编排。

---

## 5. Graph-RAG 实现

> 候选：Neo4j 自建图 / Microsoft GraphRAG / LightRAG / 自建（NetworkX+向量）

| 维度 | Neo4j 自建图 | MS GraphRAG | LightRAG | 自建 NetworkX |
|---|---|---|---|---|
| **① 检索质量提升** | ✅ 高（抽取可控、可调优） | ✅ 高（全局/多跳问题强） | ✅ 中高 | ❌ 低 |
| **② 索引成本（LLM 调用量）** | ✅ 低（本地按需抽取） | ❌ 高（索引期海量 LLM 调用） | ✅ 低（增量更新快） | ✅ 极低 |
| **③ 可控性/定制** | ✅ 最高（schema 自己定） | ❌ 黑盒 pipeline | 🟡 中 | ✅ 高 |
| **④ 可展示性（demo 亮点）** | ✅ 显式图可视化 | ❌ 无持久图 | 🟡 中 | ❌ 弱 |
| **⑤ 学习曲线/经验复用** | ✅ 已有 Neo4j 经验 | ✅ 低 | ✅ 低 | ❌ 高 |

**结论：LightRAG ✅**（爸爸猫定稿，2026-10-09）
- 内置实体/关系抽取（LLM 自动构建图）+ 图+向量一体 + 增量更新快 + 双层检索
- ⚠️ Action：回头对比 Neo4j 自建图 vs LightRAG 性能区别（Phase 2 真实数据跑基准后定是否切换）

---

## 6. 可观测（trace + 成本 + 评测）

| 维度 | Langfuse | LangSmith | OpenTelemetry+Grafana | Arize Phoenix |
|---|---|---|---|---|
| 开源/自托管 | ✅ MIT 自托管免费 | ❌ 闭源（自托管需 Enterprise） | ✅ 开源 | ✅ 开源 |
| Trace | ✅ 一等公民 | ✅（LangChain 深度） | 需自建语义 | ✅ |
| 成本追踪 | ✅ 原生 | ✅ | 自己埋 | ✅ |
| 评测（RAGAS 类） | ✅ 内置 dataset+eval | ✅ 强 | 自己拼 | ✅ |
| 框架绑定 | 无（framework-agnostic） | LangChain 深度绑定 | 无 | 无 |
| 2026 状态 | ⚠️ 2026.1 被 ClickHouse 收购，MIT 核心不变 | 闭源 | 稳定 | 稳定 |

**结论：Langfuse ✅**（2026-10-09 定稿）

---

## 7. 最终推荐技术栈（汇总，已定稿）

```
后端/编排     LangGraph（RAG + 智能路由 + Agent 状态图）
检索          Qdrant（dense+sparse 混合）+ rerank(BGE v2-m3)
Embedding     bge-m3（dense+sparse+multi-vector 三合一，本地）
生成 LLM      Claude Haiku 5.5 主力 + DeepSeek V4.1 Flash 备选（走 API，经 LiteLLM）
知识图谱      LightRAG（图+向量一体，内置实体抽取）
路由层        LiteLLM（模型路由 + 降级 + 成本追踪）
可观测        Langfuse（trace + 成本 + eval）
评测          RAGAS + HotpotQA（现成 benchmark，不自己造）
API           FastAPI
前端          Streamlit（demo 快速出效果）
部署          Docker Compose（单机一键起，可录屏）
```

---

## 8. 生成 LLM（走 API，经 LiteLLM）

> 候选：Claude Haiku 5.5 / DeepSeek V4.1 Flash / Gemini 2.5 Flash
> ✅ 已直连官方 docs 核实（2026-10-09）

| 维度 | Claude Haiku 5.5 | DeepSeek V4.1 Flash | Gemini 2.5 Flash |
|---|---|---|---|
| 成本($/M in/out) | $0.10/$0.50（≤100K；>100K $0.5/$2.5） | cache hit off-peak $0.003 in / $0.6 out | 便宜 |
| 延迟(TTFT) | 最快（官方：fastest） | 快 | 最快(0.32~0.46s) |
| RAG 生成质量 | 强（显著优于 4.5，Box AI +11分） | 强 | 强 |
| 中文能力 | 强 | ✅ 国产最强 | 强 |
| cache 折扣 | ✅ 90% | ✅ 98%（off-peak hit） | ✅ |

**结论：Claude Haiku 5.5 主力 + DeepSeek V4.1 Flash 备选**

**官方核实的关键事实（不再靠二手对比文）：**
- **Claude Haiku 5.5**（2026-10-07 刚发布，model name `claude-haiku-5-5`）：≤100K tokens 时 **$0.10/$0.50** per M（>100K 时 $0.5/$2.5），比 Haiku 4.5 便宜 ~75%；prompt caching 省 90%、batch 省 50%；有 effort controls（可调成本/智力）
- **DeepSeek V4.1 Flash**（model name `deepseek-flash`，V3/V4-flash 已 retired）：输入 cache hit off-peak **$0.003/M**（peak $0.006）、cache miss off-peak $0.15/M；输出 off-peak $0.6/M；1M context、支持 thinking/tool calls/vision
- **成本验证（都远低于 <$0.01）**：一次查询 2000 in + 300 out → Haiku 5.5 ≈ $0.0002 + $0.00015 = **$0.00035**；DeepSeek Flash cache miss ≈ $0.0003 + $0.00018 = **$0.00048**（cache hit 后 ~$0.00019）
- **分工**：Haiku 5.5 英文主力（demo 文档 K8s/AWS 是英文，远程岗面向国际）+ DeepSeek Flash 中文/降级备选；复杂 query 经 LiteLLM 路由升级旗舰（Sonnet/Opus/GPT/Gemini Pro）

---

## 9. Reranker

> 候选：BGE Reranker v2-m3 / Cohere Rerank 3 / Jina Reranker v3.5

| 维度 | BGE Reranker v2-m3 | Cohere Rerank 3 | Jina Reranker v3.5 |
|---|---|---|---|
| 质量(nDCG@10) | 强 | 最强（零配置） | 强（listwise，快） |
| 延迟 | 中 | 慢(~600ms) | 最快(<200ms) |
| 多语言 | ✅ | ✅ 100+ 语言 | ✅ |
| 部署 | ✅ 本地 Apache2.0 | ❌ API | ✅ 本地 |
| 成本 | 0 | 按量 | 0 |

**结论：BGE Reranker v2-m3 ✅（爸爸猫已拍板，2026-10-09）**
- 本地 Apache 2.0（0 成本 + 离线录屏）+ 多语言（中英）
- 和 bge-m3 embedding **同生态（BAAI）**，配置统一
- Cohere 质量最强但 API 联网 + ~600ms 慢（吃端到端延迟预算）；Jina 最快但 bge 质量/许可/生态更优
- 2026 共识：「BGE-Reranker-v2-m3 是默认选择，最佳质量/延迟/许可组合」

---

## 10. 待办 / Action

- [ ] **对比 Neo4j 自建图 vs LightRAG 性能区别**（检索质量/索引成本/延迟/可控性），Phase 2 真实数据跑基准后定是否切换
- [ ] **Simulated EKS backend + DevOps 助手**（爸爸猫初步想法）：模拟 AWS EKS 集群（含 node，可查询 node 状态/操作），结合 backend + K8s/AWS Docs 语料，做「结合 context 的 DevOps 助手」—— 呼应 Carrier EKS 经验 + 研究兴趣（边缘云编排/AI 故障检测）
