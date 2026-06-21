"""Race two (or more) models against the same prompt and print a comparison.

This is a tiny version of `llm-bench`; useful as a quick sanity check.

Run: uv run python examples/06_compare_models.py
"""

from local_llm_playground import ChatMessage, LLMClient
from local_llm_playground.utils import split_reasoning

PROMPT = (
    "Write a Python one-liner that returns the most common element in a list. "
    "Just the code, no explanation."
)

MODELS = ["deepseek-r1:14b", "hermes3:8b"]


def run(model_name: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {model_name}")
    print(f"{'=' * 60}")
    client = LLMClient(model_name)
    resp = client.chat([ChatMessage("user", PROMPT)], temperature=0.0)
    parts = split_reasoning(resp.content)
    if parts.reasoning:
        print(f"[reasoning: ~{len(parts.reasoning)} chars hidden]\n")
    print(parts.answer)
    print()
    print(f"--- {resp.elapsed_seconds:.2f}s · "
          f"{resp.usage.completion_tokens} tok · {resp.throughput:.1f} tok/s ---")


if __name__ == "__main__":
    print(f"prompt: {PROMPT}")
    for m in MODELS:
        run(m)
