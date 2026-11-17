"""Which chat model the agents use, chosen by one environment variable.

    LLM_BACKEND=anthropic   (default) Claude through the Anthropic API
    LLM_BACKEND=local       a self-hosted model behind vLLM's OpenAI-compatible API
                            (see docs/self_hosting.md)

Switching back to Claude is just unsetting LLM_BACKEND (or setting it to "anthropic").
Everything else (prompts, tools, handoffs, the verification gate) is identical on both.

For `local` the graph needs a LangChain chat model, because the voice layer's LLMAdapter wraps the
LangGraph graph. LiveKit's own OpenAI plugin can't be used here: it would replace the adapter.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

CLAUDE_MODEL = "claude-sonnet-4-6"
DEFAULT_LOCAL_URL = "http://127.0.0.1:8001/v1"
DEFAULT_LOCAL_MODEL = "qwen3.6-35b-a3b"


@dataclass(frozen=True)
class Backend:
    name: str  # "anthropic" or "local"
    model: str

    @property
    def label(self) -> str:
        return f"{self.name}:{self.model}"


def backend_name() -> str:
    name = (os.getenv("LLM_BACKEND") or "anthropic").strip().lower()
    if name not in ("anthropic", "local"):
        raise ValueError(f"LLM_BACKEND must be 'anthropic' or 'local', not {name!r}")
    return name


def make_llm(max_tokens: int, backend: str | None = None):
    """Return (chat_model, Backend). `backend` overrides LLM_BACKEND (used by the comparison eval)."""
    name = backend or backend_name()
    if name == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=CLAUDE_MODEL, max_tokens=max_tokens), Backend("anthropic", CLAUDE_MODEL)
    if name == "local":
        from langchain_openai import ChatOpenAI

        model = os.getenv("LOCAL_LLM_MODEL", DEFAULT_LOCAL_MODEL)
        llm = ChatOpenAI(
            model=model,
            base_url=os.getenv("LOCAL_LLM_BASE_URL", DEFAULT_LOCAL_URL),
            api_key="EMPTY",  # vLLM doesn't check it; the client library insists on a value
            max_tokens=max_tokens,
            # 0.2, not the server's default of 1.0: at 1.0 this model often skipped tool calls and
            # handoffs in scripted calls. Override with LOCAL_LLM_TEMPERATURE.
            temperature=float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.2")),
            # Thinking OFF on every request, as well as in the server's default: hidden reasoning
            # tokens would delay the first spoken word.
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            # Server errors should fall through to the graph's spoken fallback quickly, not hang a call.
            timeout=30,
            max_retries=0,
        )
        return llm, Backend("local", model)
    raise ValueError(f"unknown backend {name!r}")
