"""The LLM backend switch: Claude by default, the self-hosted model on request. No network."""

import pytest

from wismo.llm import CLAUDE_MODEL, make_llm
from wismo.panel import voice_turn


def test_default_backend_is_claude(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    llm, backend = make_llm(400)
    assert (backend.name, backend.model) == ("anthropic", CLAUDE_MODEL)
    assert type(llm).__name__ == "ChatAnthropic"


def test_local_backend_points_at_vllm_with_thinking_off(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "local")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:9999/v1")
    llm, backend = make_llm(400)
    assert backend.label == "local:qwen3.6-35b-a3b"
    assert type(llm).__name__ == "ChatOpenAI"
    assert llm.openai_api_base == "http://127.0.0.1:9999/v1"
    assert llm.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_unknown_backend_is_an_error(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "gpt")
    with pytest.raises(ValueError):
        make_llm(400)


def test_voice_turn_records_the_backend_only_when_given():
    assert voice_turn("assistant", {}, False, 1.0, "local:qwen3.6-35b-a3b")["backend"] == "local:qwen3.6-35b-a3b"
    assert "backend" not in voice_turn("assistant", {}, False, 1.0)
