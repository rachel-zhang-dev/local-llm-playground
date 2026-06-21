"""Multi-turn conversation: keep a growing history so the model remembers context.

Run: uv run python examples/03_multi_turn_chat.py
"""

from local_llm_playground import ChatMessage, LLMClient

client = LLMClient("hermes3:8b")

history: list[ChatMessage] = [
    ChatMessage(
        "system",
        "You are a senior Python engineer. Keep answers under 3 sentences.",
    ),
]

turns = [
    "I have a Python list of dicts. How do I sort by the 'price' key?",
    "What if the price might be missing in some dicts?",
    "And what if I want descending order?",
]

for user_msg in turns:
    print(f"\nyou › {user_msg}")
    history.append(ChatMessage("user", user_msg))
    resp = client.chat(history, temperature=0.3)
    print(f"\nhermes ›\n{resp.content}")
    history.append(ChatMessage("assistant", resp.content))

print(f"\n--- conversation kept {len(history)} messages in memory ---")
