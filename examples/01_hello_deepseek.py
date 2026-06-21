"""Simplest possible call: one prompt -> one full answer.

Run: uv run python examples/01_hello_deepseek.py
"""

from local_llm_playground import ChatMessage, LLMClient

client = LLMClient("deepseek-r1:14b")

response = client.chat(
    [ChatMessage("user", "用一句话解释什么是闭包,然后给一个 Python 例子。")]
)

print(response.content)
print()
print(f"--- meta: {response.usage.completion_tokens} tokens in "
      f"{response.elapsed_seconds:.2f}s = {response.throughput:.1f} tok/s ---")
