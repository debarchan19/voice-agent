"""Backend-specific adjustments ("fixes") for the self-hosted model, selected by backend.

Claude gets none: with `NO_TUNING` the prompts, tool schemas and graph are exactly what they were
before this module existed (tests/test_tuning.py pins that). The local backend gets the fixes that
survived the measured experiments in docs/qwen_fix_log.md.

    LLM_BACKEND=local                      Qwen with LOCAL_DEFAULT_FIXES (the measured best set)
    LOCAL_LLM_FIXES=none                   Qwen exactly as before the experiments (the baseline)
    LOCAL_LLM_FIXES=act_first,few_shot     any explicit set, for experiments

None of the fixes touches the verification gate: they change what the model is told, how the tool
schemas are worded for it, and whether a reply that claims an action without a tool call gets one
retry. Every tool call still goes through the same ToolNode and `require_verified`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# name -> experiment id in docs/qwen_fix_log.md and what it does
FIXES: dict[str, str] = {
    "act_first": "A1 prompt: call the tool in the same reply; never narrate an action without the call",
    "omit_empty_args": "A2 prompt: leave out an argument you don't have; never send None, null or empty",
    "filler_first": "A3 prompt: say 'One moment.' immediately before every tool call",
    "no_unverified_status": "A4 prompt: never state an order status no tool returned in this call",
    "few_shot": "A5 prompt: one worked example per agent of a correct tool turn (not from the test scenarios)",
    "wait_for_yes": "A6 prompt (added): hand off or change anything only after the caller confirmed the exact details",
    "qwen_tool_docs": "B2 schema: shorter tool descriptions with per-argument descriptions and allowed values",
    "plain_optional_args": "B3 schema: optional arguments shown as a plain string (no null type) and not required",
    "narration_guard": "C runtime: a reply that claims an action with no matching tool call gets one corrective retry",
}

# The set the local backend uses by default. Filled in from the experiments; see docs/qwen_fix_log.md.
LOCAL_DEFAULT_FIXES: frozenset[str] = frozenset({"act_first", "omit_empty_args", "no_unverified_status", "narration_guard"})


@dataclass(frozen=True)
class Tuning:
    fixes: frozenset[str] = frozenset()

    def __post_init__(self):
        unknown = set(self.fixes) - set(FIXES)
        if unknown:
            raise ValueError(f"unknown fix(es) {sorted(unknown)}; known: {sorted(FIXES)}")

    def has(self, name: str) -> bool:
        return name in self.fixes

    @property
    def label(self) -> str:
        return ",".join(sorted(self.fixes)) or "none"


NO_TUNING = Tuning()


def parse_fixes(raw: str | None) -> Tuning:
    """'none' -> no fixes; 'default' or empty -> LOCAL_DEFAULT_FIXES; otherwise a comma-separated list."""
    raw = (raw or "default").strip().lower()
    if raw == "none":
        return NO_TUNING
    if raw == "default":
        return Tuning(LOCAL_DEFAULT_FIXES)
    names = {x.strip() for x in raw.replace("+", ",").split(",") if x.strip()}
    if "default" in names:
        names = (names - {"default"}) | LOCAL_DEFAULT_FIXES
    return Tuning(frozenset(names))


def tuning_for(backend_name: str) -> Tuning:
    """Claude: never any fixes. Local: LOCAL_LLM_FIXES if set, else the measured default."""
    if backend_name == "anthropic":
        return NO_TUNING
    return parse_fixes(os.getenv("LOCAL_LLM_FIXES"))
