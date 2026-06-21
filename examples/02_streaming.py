"""Stream tokens as they arrive, instead of waiting for the full response.

Useful for: interactive UIs, perceived latency, watching DeepSeek-R1 think.

Run: uv run python examples/02_streaming.py
"""

import sys
import time

from local_llm_playground import ChatMessage, LLMClient

client = LLMClient("deepseek-r1:14b")

t0 = time.perf_counter()
first_token_at: float | None = None
total_tokens = 0

for chunk in client.chat_stream(
    [ChatMessage("user", "Write a haiku about M-series Mac fans (or lack thereof).")]
):
    if chunk.delta and first_token_at is None:
        first_token_at = time.perf_counter() - t0
    sys.stdout.write(chunk.delta)
    sys.stdout.flush()
    if chunk.done and chunk.usage:
        total_tokens = chunk.usage.completion_tokens

elapsed = time.perf_counter() - t0
print()
print()
print(f"--- TTFT: {first_token_at:.3f}s · total: {elapsed:.2f}s · "
      f"{total_tokens} tokens · {total_tokens / elapsed:.1f} tok/s ---")
