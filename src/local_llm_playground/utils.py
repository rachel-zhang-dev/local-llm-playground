"""Small helpers shared by client/cli/benchmark."""

from __future__ import annotations

import re
from dataclasses import dataclass

THINK_PATTERN = re.compile(r"<think>(.*?)</think>", re.DOTALL)


@dataclass(frozen=True)
class SplitResult:
    """Result of separating reasoning trace from final answer."""

    reasoning: str
    answer: str


def split_reasoning(text: str) -> SplitResult:
    """Pull `<think>...</think>` blocks out of a DeepSeek-R1 style response.

    DeepSeek-R1 (and similar reasoning models) emit their chain-of-thought
    wrapped in `<think>` tags before producing the final user-facing answer.
    """
    matches = THINK_PATTERN.findall(text)
    reasoning = "\n\n".join(m.strip() for m in matches).strip()
    answer = THINK_PATTERN.sub("", text).strip()
    return SplitResult(reasoning=reasoning, answer=answer)


def format_throughput(tokens: int, seconds: float) -> str:
    """Format tokens/s nicely, handling zero-duration edge cases."""
    if seconds <= 0:
        return "n/a"
    return f"{tokens / seconds:.1f} tok/s"
