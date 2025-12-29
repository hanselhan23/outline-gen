"""Simple usage tracker for LLM calls (tokens and cost estimation helper).

This module does not depend on any particular CLI or output framework.
It only aggregates prompt/completion token usage by model. The CLI is
responsible for reading pricing configuration and rendering summaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any


@dataclass
class ModelUsage:
    """Aggregated usage for a single model."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class UsageTracker:
    """In-memory tracker for token usage, grouped by model name."""

    def __init__(self) -> None:
        self._by_model: Dict[str, ModelUsage] = {}

    def reset(self) -> None:
        self._by_model.clear()

    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        if not model:
            model = "unknown"
        usage = self._by_model.get(model)
        if not usage:
            usage = ModelUsage()
            self._by_model[model] = usage
        usage.prompt_tokens += int(prompt_tokens or 0)
        usage.completion_tokens += int(completion_tokens or 0)

    def summary(self) -> Dict[str, Dict[str, int]]:
        """Return a plain dict summary suitable for printing/logging."""
        return {
            model: {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
            for model, usage in self._by_model.items()
        }


global_usage_tracker = UsageTracker()


def _extract_usage(usage: Any) -> Dict[str, int]:
    """Best-effort extraction of prompt/completion tokens from a usage object."""
    if usage is None:
        return {"prompt_tokens": 0, "completion_tokens": 0}

    # OpenAI style object with attributes
    prompt = getattr(usage, "prompt_tokens", None)
    completion = getattr(usage, "completion_tokens", None)

    # Dict-like fallback
    if prompt is None and isinstance(usage, dict):
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")

    return {
        "prompt_tokens": int(prompt or 0),
        "completion_tokens": int(completion or 0),
    }


def record_chat_completion_usage(model: str, response: Any) -> None:
    """Helper to record usage from an OpenAI chat.completions response."""
    usage = getattr(response, "usage", None)
    tokens = _extract_usage(usage)
    if tokens["prompt_tokens"] or tokens["completion_tokens"]:
        global_usage_tracker.record(
            model=model,
            prompt_tokens=tokens["prompt_tokens"],
            completion_tokens=tokens["completion_tokens"],
        )

