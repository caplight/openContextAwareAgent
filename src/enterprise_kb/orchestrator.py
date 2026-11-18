"""编排层：把评估闭环的散件串成完整流程（Orchestrator 角色）。

设计见 `docs/mvp-design.md` §10 时序图。

核心增量价值（散件之外的编排）：
1. `suggest_top_k_workflow`：跑多组 top_k 评估 → 收集 scores → `suggest_top_k`（步骤 19-22）
2. `apply_suggestion`：用户确认后写回 `assistant_config`（步骤 23-26）

其余步骤（上传 PDF / 种子问题 / 单轮评估 / 记录评分）都直接调现有模块，
不做重复封装（薄封装无增量价值）：
- 上传 → `ingest.load_and_split()` + `embed.index_chunks()`
- 种子问题 → `seed_questions.generate_seed_questions()`
- 单轮评估 → `evaluate.run_evaluation()`
- 评分 → `rating.Rating`（前端直接构造）
"""

from __future__ import annotations

from enterprise_kb.assistant import (
    AssistantConfig,
    ResolvedConfig,
    get_resolved_config,
    upsert_assistant_config,
)
from enterprise_kb.evaluate import run_evaluation
from enterprise_kb.logging import get_logger
from enterprise_kb.rating import Rating
from enterprise_kb.seed_questions import SeedQuestion
from enterprise_kb.suggest import Suggestion, suggest_top_k

logger = get_logger(__name__)

# 候选 top_k 值（Greedy-M 试几组，报告趋势）
_DEFAULT_CANDIDATES = (3, 5, 8, 10)


def suggest_top_k_workflow(
    assistant_id: str,
    questions: list[SeedQuestion],
    ratings: list[Rating] | None = None,
    candidates: tuple[int, ...] = _DEFAULT_CANDIDATES,
) -> Suggestion | None:
    """最小闭环的「建议」编排：跑多组 top_k 评估 → 收集 scores → suggest。

    Args:
        assistant_id: 助手 id（读当前 top_k）。
        questions: 种子问题（对每组候选值都跑一遍评估）。
        ratings: 用户评分（用于置信度样本量）。
        candidates: 候选 top_k 值。

    Returns:
        `Suggestion`（建议调到最优 top_k），或 `None`（无需调整）。
    """
    cfg = get_resolved_config(assistant_id)
    current = cfg.top_k

    scores: dict[int, float] = {}
    for k in candidates:
        trial_cfg = cfg.model_copy(update={"top_k": k})
        run = run_evaluation(questions, config=trial_cfg)
        scores[k] = run.avg_faithfulness
        logger.info("top_k=%d → avg_faithfulness=%.3f", k, run.avg_faithfulness)

    return suggest_top_k(current, scores, ratings)


def apply_suggestion(assistant_id: str, suggestion: Suggestion) -> ResolvedConfig:
    """用户确认后写回配置（只覆盖建议涉及的参数）。

    Args:
        assistant_id: 助手 id。
        suggestion: 用户确认采纳的建议。

    Returns:
        写回后的 `ResolvedConfig`（供前端展示「更新后的配置生效」）。
    """
    # 只写建议涉及的参数（MVP 固定 top_k），其余字段不动（回退全局）
    update = AssistantConfig(top_k=suggestion.recommended)
    upsert_assistant_config(assistant_id, update)
    logger.info(
        "已采纳建议：%s %s→%s（置信度 %.2f）",
        suggestion.param,
        suggestion.current,
        suggestion.recommended,
        suggestion.confidence,
    )
    return get_resolved_config(assistant_id)
