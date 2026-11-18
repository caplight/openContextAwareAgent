"""orchestrator 测试：编排逻辑（跑多组评估 + 建议 + 写回）。"""

from __future__ import annotations

from types import SimpleNamespace

from enterprise_kb import orchestrator
from enterprise_kb.assistant import AssistantConfig, resolve
from enterprise_kb.rating import Rating
from enterprise_kb.seed_questions import SeedQuestion
from enterprise_kb.suggest import Suggestion


def _cfg(top_k):
    return resolve(AssistantConfig(top_k=top_k))


def _questions(n: int = 3) -> list[SeedQuestion]:
    return [SeedQuestion(question=f"q{i}", expected_answer=f"a{i}") for i in range(n)]


# 候选 top_k → avg_faithfulness（8 最优）
_SCORES = {3: 0.60, 5: 0.71, 8: 0.82, 10: 0.75}


def _mock_run_eval(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "run_evaluation",
        lambda q, config=None: SimpleNamespace(avg_faithfulness=_SCORES[config.top_k]),
    )


def test_suggest_workflow_collects_scores_and_recommends(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_resolved_config", lambda aid: _cfg(5))
    _mock_run_eval(monkeypatch)

    ratings = [Rating(question="q0", rating="up")] * 12
    s = orchestrator.suggest_top_k_workflow("aid", _questions(), ratings)

    assert s is not None
    assert s.current == 5
    assert s.recommended == 8  # 最高分
    assert s.confidence > 0.5  # 12 条评分 → ~0.63


def test_suggest_workflow_no_change_needed(monkeypatch):
    # 当前 top_k=8 已是候选里最优 → 返回 None
    monkeypatch.setattr(orchestrator, "get_resolved_config", lambda aid: _cfg(8))
    _mock_run_eval(monkeypatch)

    s = orchestrator.suggest_top_k_workflow("aid", _questions())
    assert s is None


def test_suggest_workflow_evaluates_all_candidates(monkeypatch):
    """验证对每个候选 top_k 都跑了一遍评估。"""
    evaluated = []
    monkeypatch.setattr(orchestrator, "get_resolved_config", lambda aid: _cfg(5))

    def _run_eval(q, config=None):
        evaluated.append(config.top_k)
        return SimpleNamespace(avg_faithfulness=_SCORES[config.top_k])

    monkeypatch.setattr(orchestrator, "run_evaluation", _run_eval)

    orchestrator.suggest_top_k_workflow("aid", _questions())
    assert sorted(evaluated) == [3, 5, 8, 10]


def test_apply_suggestion_writes_top_k(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        orchestrator,
        "upsert_assistant_config",
        lambda aid, cfg: captured.update({"aid": aid, "top_k": cfg.top_k}),
    )
    monkeypatch.setattr(orchestrator, "get_resolved_config", lambda aid: _cfg(8))

    s = Suggestion(param="top_k", current=5, recommended=8, reason="...", confidence=0.6)
    resolved = orchestrator.apply_suggestion("aid", s)

    assert captured["aid"] == "aid"
    assert captured["top_k"] == 8
    assert resolved.top_k == 8
