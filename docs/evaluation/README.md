# 评测基线与测试集说明

> 本文档是「Phase 1 vs Phase 2 KPI 对比」的**唯一事实来源**，固定测试集 + 对比协议，保证各阶段分数可公平对比、可复现。

## 1. 测试集（固定，不可变）

| 项 | 值 |
|----|----|
| 来源 | HotpotQA `distractor` 配置，`validation` split |
| 加载方式 | `datasets` 库 `load_dataset("hotpotqa/hotpot_qa", "distractor", split="validation")` 顺序取前 50 条 |
| 样本数 | **50 条**（固定） |
| 落盘文件 | `data/eval/hotpotqa_sample.json` |
| 生成脚本 | `eval/build_dataset.py` |

**为什么固定 50 条（而非更少）**：统计更稳健，避免小样本偶然性；测试集文件本就生成 50 条，Phase 1 早期只跑了前 20 条属临时基线，已重跑补齐到 50 条。

**确定性说明**：HotpotQA 数据文件固定，`datasets` 顺序加载是确定的 → 前 50 条样本在任意时间、任意环境都一致。

**样本结构**：每条含 `question` / `answer`（ground truth）/ `context`（`{"title": [...], "sentences": [[...], ...]}`）/ `supporting_facts`。

## 2. 对比协议（Phase 1 / Phase 2 共用）

为了让不同阶段的分数**可比**，以下要素跨阶段固定：

| 要素 | 固定值 |
|------|--------|
| 测试集 | 上述 50 条（同一文件、同一顺序） |
| LLM judge | `deepseek-chat`（RAGAS 的 faithfulness / context_precision 打分模型） |
| 评测指标 | `faithfulness` + `context_precision`（answer_relevancy 暂未启用，因需额外 embeddings 配置） |
| 生成 LLM | Phase 1 为 `deepseek/deepseek-flash`（无 Anthropic key 时 fallback） |

**可变项（这才是 Phase 演进点）**：

| 阶段 | 检索方式 | 说明 |
|------|----------|------|
| Phase 1 | bge-m3 纯向量 top-3 | naive baseline |
| Phase 2 | 混合检索（BM25+dense）+ Reranker + Graph-RAG（LightRAG） | 优化检索质量 |

## 3. 复现方法

```bash
cd demo
export UV_PROJECT_ENVIRONMENT=/root/.venvs/enterprise-kb
export DEEPSEEK_API_KEY=sk-xxx          # 生成 + judge 用
unset ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY http_proxy https_proxy

# （可选）重新生成测试集
uv run python eval/build_dataset.py 50

# 跑 Phase 1 naive baseline（默认 50 条）
uv run python eval/eval_ragas.py 50
```

## 4. 各阶段结果汇总

| 阶段 | 文件 | faithfulness | context_precision |
|------|------|-------------|-------------------|
| Phase 1 naive | `phase1-naive-baseline.md` | 见文件 | 见文件 |
| Phase 2 混合检索 | `phase2-hybrid-rerank-graphrag.md`（待产出） | — | — |

> 每阶段跑完更新此表 + 对应结果文件，形成「baseline → 优化」的完整演进曲线（面试可直接引用）。
