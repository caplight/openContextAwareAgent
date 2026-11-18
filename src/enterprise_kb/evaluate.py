"""评估（评估闭环核心）：对每个种子问题跑 retrieve + generate + RAGAS 打分。

设计见 `docs/mvp-design.md` §4.2。

复用：
- `retrieve_hybrid`（Qdrant 检索，`src/retrieve.py`）
- `generate_answer`（生成，`src/generate.py`）
- RAGAS `faithfulness` / `context_precision`（打分，抽自 `eval/eval_ragas.py`）

关键决策：
- **串行打分**（RAGAS 内部并发会死锁，复用 `eval_ragas.py` 的经验，不并发）
- judge LLM 用 `deepseek-chat`（与 `eval_ragas.py` 一致）
- **不持久化**（返回内存 `EvaluationRun`，存储由后续 `storage_eval.py` 负责）
- `config_snapshot` 存 `ResolvedConfig.model_dump()`，供后续 diff 对比
"""

from __future__ import annotations

from openai import OpenAI
from pydantic import BaseModel, Field
from ragas.dataset_schema import SingleTurnSample
from ragas.llms import llm_factory
from ragas.metrics import context_precision, faithfulness

from enterprise_kb.assistant import ResolvedConfig, get_resolved_config
from enterprise_kb.config import get_settings
from enterprise_kb.generate import generate_answer
from enterprise_kb.logging import get_logger
from enterprise_kb.retrieve import retrieve_hybrid
from enterprise_kb.seed_questions import SeedQuestion

logger = get_logger(__name__)


class EvaluationResult(BaseModel):
    """一个种子问题的评估结果。"""

    question: str
    expected_answer: str | None = None
    answer: str
    contexts: list[str] = Field(default_factory=list)
    faithfulness: float = 0.0
    context_precision: float = 0.0


class EvaluationRun(BaseModel):
    """一轮评估：所有问题的结果 + 本次用的配置快照。"""

    results: list[EvaluationResult] = Field(default_factory=list)
    config_snapshot: dict = Field(default_factory=dict)

    @property
    def avg_faithfulness(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.faithfulness for r in self.results) / len(self.results)

    @property
    def avg_context_precision(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.context_precision for r in self.results) / len(self.results)


def _build_judge_llm(model: str = "deepseek-chat"):
    """构建 RAGAS judge LLM（deepseek-chat）。抽自 eval_ragas.py。"""
    settings = get_settings()
    key = settings.deepseek_api_key.get_secret_value() if settings.deepseek_api_key else ""
    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")
    return llm_factory(model, client=client)


def _score_ragas(question: str, answer: str, contexts: list[str], reference: str) -> tuple[float, float]:
    """RAGAS 打分：faithfulness（忠实度）+ context_precision（上下文精度）。"""
    fs = SingleTurnSample(user_input=question, response=answer, retrieved_contexts=contexts)
    f = float(faithfulness.single_turn_score(fs))

    cps = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts,
        reference=reference,
    )
    cp = float(context_precision.single_turn_score(cps))
    return f, cp


def run_evaluation(
    questions: list[SeedQuestion],
    config: ResolvedConfig | None = None,
    judge_model: str = "deepseek-chat",
) -> EvaluationRun:
    """对每个种子问题跑 retrieve + generate + RAGAS 打分（串行）。

    Args:
        questions: 种子问题（含 expected_answer，作 context_precision 的 reference）。
        config: 已 resolve 的助手配置（None 时用全局默认）。
        judge_model: RAGAS judge LLM 名称。

    Returns:
        EvaluationRun（含每条结果 + config_snapshot）。
    """
    cfg = config or get_resolved_config(None)

    # RAGAS 打分前设置 judge LLM（全局单例，跑前设置一次）
    judge_llm = _build_judge_llm(judge_model)
    faithfulness.llm = judge_llm
    context_precision.llm = judge_llm

    results: list[EvaluationResult] = []
    for i, q in enumerate(questions, start=1):
        contexts = retrieve_hybrid(q.question, top_k=cfg.top_k)
        answer = generate_answer(q.question, contexts, model=cfg.generative_model).content
        f, cp = _score_ragas(q.question, answer, contexts, q.expected_answer or "")
        results.append(
            EvaluationResult(
                question=q.question,
                expected_answer=q.expected_answer,
                answer=answer,
                contexts=contexts,
                faithfulness=f,
                context_precision=cp,
            )
        )
        logger.info("[%d/%d] faithfulness=%.3f context_precision=%.3f", i, len(questions), f, cp)

    run = EvaluationRun(results=results, config_snapshot=cfg.model_dump())
    logger.info(
        "评估完成：avg_faithfulness=%.3f avg_context_precision=%.3f",
        run.avg_faithfulness,
        run.avg_context_precision,
    )
    return run
