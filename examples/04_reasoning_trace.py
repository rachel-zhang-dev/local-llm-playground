"""Show the <think>...</think> reasoning chain produced by DeepSeek-R1.

R1-style models emit their internal chain-of-thought inside `<think>` tags
before the final answer. This example separates the two.

Run: uv run python examples/04_reasoning_trace.py
"""

from local_llm_playground import ChatMessage, LLMClient
from local_llm_playground.utils import split_reasoning

PROMPT = (
    "A snail climbs a 30-foot wall. Each day it climbs 3 feet but slides back "
    "2 feet at night. On which day does it reach the top? "
    "Think step by step, but be brief."
)

client = LLMClient("deepseek-r1:14b")
resp = client.chat([ChatMessage("user", PROMPT)], temperature=0.2)

parts = split_reasoning(resp.content)

print("=" * 70)
print("REASONING (hidden chain-of-thought):")
print("=" * 70)
print(parts.reasoning or "(none — model did not emit <think> tags)")
print()
print("=" * 70)
print("FINAL ANSWER (what the user sees):")
print("=" * 70)
print(parts.answer)
print()
print(f"--- {resp.usage.completion_tokens} tokens total, "
      f"reasoning is ~{len(parts.reasoning)} chars of {len(resp.content)} ---")
