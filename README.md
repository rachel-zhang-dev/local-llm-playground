# local-llm-playground

A small, hands-on POC for talking to **local** (Ollama: DeepSeek-R1, Hermes 3, gpt-oss) and **cloud** (OpenAI, Xiaomi MiMo UltraSpeed) LLMs through one unified Python client.

Built on a MacBook Pro M4 / 24 GB unified memory, but works on any machine with Ollama.

## What's in it

| Layer | File | What it does |
|---|---|---|
| Config | `config.py` | Model registry: name → provider, endpoint, env vars |
| Client | `client.py` | One `LLMClient` API that hides Ollama vs OpenAI-compatible |
| CLI | `cli.py` | Interactive chat REPL (rich UI, streaming, slash commands) |
| Server | `api.py` | FastAPI server exposing local models as OpenAI-compatible `/v1/chat/completions` |
| Bench | `benchmark.py` | Race N models on the same prompt, print a comparison table |
| Examples | `examples/` | Six tiny scripts that show one feature each |

## Prerequisites

1. **Ollama** running locally (`ollama serve` or via `brew services start ollama`)
2. At least one model pulled:
   ```bash
   ollama pull deepseek-r1:14b
   ollama pull hermes3:8b
   ```
3. **uv** for Python dependency management

## Setup

```bash
git clone https://github.com/rachel-zhang-dev/local-llm-playground.git
cd local-llm-playground
uv sync                       # creates .venv, installs deps
cp .env.example .env          # optional: fill in cloud API keys later
```

## Quick start

### 1. Interactive chat with DeepSeek-R1

```bash
uv run llm-chat
# or pick a different model
uv run llm-chat --model hermes3:8b
```

Inside the REPL:

```
/model hermes3:8b    switch model mid-conversation
/system "you are X"  set system prompt
/reset               clear history
/stream              toggle streaming
/reasoning           toggle showing <think> trace
/quit                exit
```

### 2. Benchmark two models on the same prompt

```bash
uv run llm-bench \
  --prompt "Write a Python one-liner that returns the most common element in a list." \
  --models deepseek-r1:14b,hermes3:8b \
  --runs 3
```

You get latency, token throughput, and answer previews side by side.

### 3. Serve local models as OpenAI API

```bash
uv run llm-serve --model deepseek-r1:14b --port 8080
```

Now point any OpenAI-compatible client at `http://localhost:8080/v1`:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "deepseek-r1:14b",
    "messages": [{"role": "user", "content": "hi"}]
  }'
```

Use cases:
- Point **Codex CLI** or **Cursor** at your local DeepSeek (free, private)
- Wire **chatgpt-on-wechat** or **AstrBot** to a local model
- Drop-in replacement for OpenAI in any prototype

### 4. Run the examples

```bash
uv run python examples/01_hello_deepseek.py     # minimal call
uv run python examples/02_streaming.py          # streaming tokens
uv run python examples/03_multi_turn_chat.py    # multi-turn history
uv run python examples/04_reasoning_trace.py    # parse <think> from R1
uv run python examples/05_function_calling.py   # tool use with Hermes 3
uv run python examples/06_compare_models.py     # head-to-head
```

## Adding a new model

Edit `src/local_llm_playground/config.py` and append a `ModelConfig` entry:

```python
"my-new-model": ModelConfig(
    name="my-new-model",
    provider=Provider.OPENAI_COMPATIBLE,
    model_id="real-model-id-at-provider",
    base_url="https://api.example.com/v1",
    api_key_env="MY_API_KEY",
    description="...",
),
```

That's it; the CLI, server, and benchmark pick it up automatically.

## Roadmap

- [x] Phase 1: DeepSeek-R1 + Hermes 3 local, unified client, examples
- [ ] Phase 2: add Xiaomi MiMo UltraSpeed (cloud) once trial access is approved, compare 1000 tps claim against local 14B
- [ ] Phase 3: optional Next.js front-end matching `data-copilot` style

## Why this project exists

I wanted one place to:

1. Confirm DeepSeek-R1 and Hermes 3 actually run usably on my M4 / 24 GB Mac
2. Have a real, working "what does an OpenAI-compatible API look like" reference
3. Test MiMo UltraSpeed against a local baseline as soon as the trial activates
4. Reuse the same code to wire LLMs into other tools (Codex, WeChat bots, etc.)

If any of that is useful to you, feel free to fork.

## License

MIT
