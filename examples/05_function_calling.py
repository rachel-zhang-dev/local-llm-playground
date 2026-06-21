"""Tool / function calling: the model decides when to invoke a function.

Ollama supports tool calling via the same `tools` field as OpenAI. Hermes 3
was fine-tuned with strong tool-use behavior, so we use it here.

Run: uv run python examples/05_function_calling.py
"""

import json

from ollama import Client as OllamaClient

from local_llm_playground.config import get_model


def get_weather(city: str, unit: str = "celsius") -> dict:
    """Pretend to look up weather. In reality we just return a stub."""
    fake_data = {
        "shanghai": {"temp": 28, "condition": "humid + cloudy"},
        "tokyo": {"temp": 24, "condition": "clear"},
        "san francisco": {"temp": 17, "condition": "foggy"},
    }
    data = fake_data.get(city.lower(), {"temp": 20, "condition": "unknown"})
    return {"city": city, "unit": unit, **data}


tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                    "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                },
                "required": ["city"],
            },
        },
    }
]


cfg = get_model("hermes3:8b")
client = OllamaClient(host=cfg.base_url)

messages = [
    {"role": "user", "content": "What's the weather in Shanghai and Tokyo today?"},
]

print("[round 1] sending to model with tools available...")
resp = client.chat(model=cfg.model_id, messages=messages, tools=tools)
msg = resp["message"]
messages.append(msg)

tool_calls = msg.get("tool_calls", [])
if not tool_calls:
    print("\n(model chose not to call any tool)")
    print(f"reply: {msg.get('content', '')}")
    raise SystemExit(0)

print(f"\nmodel wants to call {len(tool_calls)} tool(s):")
for call in tool_calls:
    fn = call["function"]
    args = fn["arguments"]
    if isinstance(args, str):
        args = json.loads(args)
    print(f"  -> {fn['name']}({args})")

    result = get_weather(**args)
    print(f"     result: {result}")
    messages.append(
        {
            "role": "tool",
            "content": json.dumps(result),
            "name": fn["name"],
        }
    )

print("\n[round 2] sending tool results back...")
final = client.chat(model=cfg.model_id, messages=messages)
print(f"\nfinal answer:\n{final['message']['content']}")
