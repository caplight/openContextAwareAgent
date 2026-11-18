"""evaluate 测试：评估编排逻辑（mock 检索/生成/judge/打分）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from enterprise_kb import evaluate
from enterprise_kb.assistant import AssistantConfig, ResolvedConfig, resolve
from enterprise_kb.evaluate import EvaluationRun, EvaluationResult
from enterprise_kb.seed_questions import SeedQuestion


def make_questions(n: int = 3) -> list[SeedQuestion]:
    return [
        SeedQuestion(
            question=f"问题 {i}",
            expected_answer=f"期望答案 {i}",
            source_chunk_ids=[f"chunk-{i}"],
        )
        for i in range(n)
    ]


def _mock_deps(monkeypatch, *, contexts=None, scores=None):
    """统一 mock 四个依赖：retrieve / generate / judge / score。"""
    ctx = contexts or ["片段A", "片段B"]
    sc = scores or (0.8, 0.7)

    monkeypatch.setattr(evaluate, "retrieve_hybrid", lambda q, top_k=None: ctx)
    monkeypatch.setattr(
        evaluate, "generate_answer", lambda q, c, model=None: SimpleNamespace(content="生成的答案")
    )
    monkeypatch.setattr(evaluate, "_build_judge_llm", lambda model=None: None)
    monkeypatch.setattr(evaluate, "_score_ragas", lambda q, a, c, ref: sc)
    return ctx, sc


def test_run_evaluation_basic(monkeypatch):
    ctx, sc = _mock_deps(monkeypatch)
    qs = make_questions(3)

    run = evaluate.run_evaluation(qs)
    assert isinstance(run, EvaluationRun)
    assert len(run.results) == 3
    for r in run.results:
        assert isinstance(r, EvaluationResult)
        assert r.answer == "生成的答案"
        assert r.contexts == ctx
        assert r.faithfulness == sc[0]
        assert r.context_precision == sc[1]


def test_run_evaluation_avg(monkeypatch):
    # 每条打分不同，验证平均值计算
    scores = iter([(0.8, 0.7), (0.6, 0.5), (0.4, 0.3)])

    def _score(q, a, c, ref):
        return next(scores)

    _mock_deps(monkeypatch)
    monkeypatch.setattr(evaluate, "_score_ragas", _score)

    run = evaluate.run_evaluation(make_questions(3))
    assert run.avg_faithfulness == pytest.approx((0.8 + 0.6 + 0.4) / 3)
    assert run.avg_context_precision == pytest.approx((0.7 + 0.5 + 0.3) / 3)


def test_run_evaluation_empty(monkeypatch):
    _mock_deps(monkeypatch)
    run = evaluate.run_evaluation([])
    assert run.results == []
    assert run.avg_faithfulness == 0.0
    assert run.avg_context_precision == 0.0


def test_config_snapshot_records_config(monkeypatch):
    _mock_deps(monkeypatch)
    cfg = resolve(AssistantConfig(top_k=8, generative_model="deepseek/deepseek-flash"))

    run = evaluate.run_evaluation(make_questions(1), config=cfg)
    snap = run.config_snapshot
    assert snap["top_k"] == 8
    assert snap["generative_model"] == "deepseek/deepseek-flash"


def test_uses_config_top_k_and_model(monkeypatch):
    """验证 run_evaluation 把 config 的 top_k / generative_model 传给检索/生成。"""
    captured = {}

    def _retrieve(q, top_k=None):
        captured["top_k"] = top_k
        return ["片段"]

    def _generate(q, c, model=None):
        captured["model"] = model
        return SimpleNamespace(content="答案")

    monkeypatch.setattr(evaluate, "retrieve_hybrid", _retrieve)
    monkeypatch.setattr(evaluate, "generate_answer", _generate)
    monkeypatch.setattr(evaluate, "_build_judge_llm", lambda model=None: None)
    monkeypatch.setattr(evaluate, "_score_ragas", lambda q, a, c, ref: (0.8, 0.7))

    cfg = resolve(AssistantConfig(top_k=6, generative_model="deepseek/deepseek-flash"))
    evaluate.run_evaluation(make_questions(1), config=cfg)

    assert captured["top_k"] == 6
    assert captured["model"] == "deepseek/deepseek-flash"
