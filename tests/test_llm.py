"""LLM 层测试：primary → fallback 降级逻辑（mock litellm）。"""

from __future__ import annotations

from types import SimpleNamespace

from enterprise_kb.llm import generate


def _fake_resp(content: str, model: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


def test_primary_success(mocker):
    mock = mocker.patch("enterprise_kb.llm.litellm.completion")
    mock.return_value = _fake_resp("answer", "claude-haiku-5-5")

    result = generate([{"role": "user", "content": "hi"}])
    assert result.content == "answer"
    assert result.model == "claude-haiku-5-5"
    assert result.prompt_tokens == 10


def test_fallback_when_primary_fails(mocker):
    mock = mocker.patch("enterprise_kb.llm.litellm.completion")

    def side_effect(model, **kwargs):
        if model == "claude-haiku-5-5":
            raise RuntimeError("primary down")
        return _fake_resp("fallback answer", model)

    mock.side_effect = side_effect

    result = generate([{"role": "user", "content": "hi"}])
    assert result.model == "deepseek/deepseek-flash"
    assert result.content == "fallback answer"


def test_all_models_fail_raises(mocker):
    mock = mocker.patch("enterprise_kb.llm.litellm.completion")
    mock.side_effect = RuntimeError("all down")

    import pytest

    with pytest.raises(RuntimeError):
        generate([{"role": "user", "content": "hi"}])
