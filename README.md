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

## Benchmark results

A 5-prompt × 3-model bench (`benchmarks/run.py`, full report in [`benchmarks/REPORT.md`](benchmarks/REPORT.md)) on a MacBook Pro M4 / 24 GB unified memory:

| Model | Avg throughput | Avg latency | Avg out tokens |
|---|---:|---:|---:|
| `gpt-oss:20b` | **16.4 tok/s** ⚡ | 29.4s | 514 |
| `deepseek-r1:14b` | 9.5 tok/s | 61.7s | 602 |
| `hermes3:8b` | 5.6 tok/s | **12.8s** ⚡ | 82 |

Takeaways from the run:

- **`gpt-oss:20b` is fastest on M-series despite being the biggest.** Counter-intuitive but real: its Q4 quantization is tuned for Apple Silicon and it consistently outpaces the smaller 14B and 8B models in tokens/sec.
- **`hermes3:8b` wins wall-clock time, because it doesn't "think".** It emits short, direct answers and is back in ~13 s. The catch: it got the classic snail-on-wall puzzle wrong (said Day 31; correct answer is Day 28). Reasoning models got it right.
- **`deepseek-r1:14b` spends ~80% of its tokens inside `<think>`.** Great for puzzles, but you'll want a generous `max_tokens` (1200+) on agentic / code-review tasks or it runs out of room before producing a final answer.
- **Pick by task**, not by size:
  - Code completion / refactor → `hermes3:8b` (fast, concise, ~no reasoning overhead)
  - Logic puzzles / math / multi-step reasoning → `deepseek-r1:14b` or `gpt-oss:20b`
  - Agent / tool-calling backend for Codex CLI → `hermes3:8b` or `gpt-oss:20b` (DeepSeek-R1 doesn't expose tools)

Re-run any time:

```bash
uv run python benchmarks/run.py
# or pick subsets:
uv run python benchmarks/run.py --models hermes3:8b,gpt-oss:20b --prompts logic-snail,bug-find
```

## Wiring Codex CLI to a local Ollama model

OpenAI's `codex` CLI has built-in OSS support via `--oss --local-provider ollama`. The interesting bits below are the gotchas you hit on macOS in 2026.

### What works and what doesn't

| Model | Tool calling? | Usable as Codex backend? |
|---|---|---|
| `deepseek-r1:14b` | ❌ Ollama returns "does not support tools" | No |
| `hermes3:8b` | ✅ Fine-tuned for tool use | **Yes (recommended)** |
| `gpt-oss:20b` | ✅ | Yes (slower, stronger) |
| `deepseek-r1:latest` (7B distill) | ❌ | No |
| `llama3.2:latest` | ✅ | Yes (small/fast) |

Codex needs tool calling to read files, run commands, etc. R1-style reasoning models don't expose tool-use heads, so they can't drive an agent loop even though they're great at pure reasoning.

### Two gotchas you'll hit

**1. macOS system proxy intercepts localhost.** If you run Clash / Surge / V2Ray, the macOS HTTP proxy setting catches Python's `httpx` and Codex's Rust HTTP client too. You'll see `503 Service Unavailable` from a perfectly healthy Ollama. Fix: tell every client to bypass localhost.

```bash
export NO_PROXY="localhost,127.0.0.1,::1"
export no_proxy="$NO_PROXY"
```

**2. `codex exec` blocks on stdin** when invoked with a prompt argument. Redirect stdin from `/dev/null` for non-interactive use:

```bash
codex exec --oss --local-provider ollama --model hermes3:8b \
  --skip-git-repo-check "your prompt" < /dev/null
```

### Ship it: shell functions you can keep

Drop this into `~/.zshrc` (already done on the author's box):

```bash
export NO_PROXY="localhost,127.0.0.1,::1${NO_PROXY:+,$NO_PROXY}"
export no_proxy="$NO_PROXY"

codex-local() {
  if [ $# -eq 0 ]; then
    command codex --oss --local-provider ollama --model hermes3:8b
  else
    command codex exec --oss --local-provider ollama --model hermes3:8b \
      --skip-git-repo-check "$@" < /dev/null
  fi
}
codex-local-big() {
  if [ $# -eq 0 ]; then
    command codex --oss --local-provider ollama --model gpt-oss:20b
  else
    command codex exec --oss --local-provider ollama --model gpt-oss:20b \
      --skip-git-repo-check "$@" < /dev/null
  fi
}
```

Then use it just like `codex`:

```bash
# interactive TUI, backed by local Hermes 3
codex-local

# one-shot, backed by local Hermes 3
codex-local "explain the difference between async and await in Python"

# one-shot, backed by gpt-oss 20B (slower, stronger)
codex-local-big "refactor this function to be tail-recursive"
```

### Verified on this machine

- MacBook Pro M4 / 24 GB unified memory / macOS Sequoia 15.6.1
- Codex 0.141.0, Ollama 0.24.0, Hermes 3 8B
- "What is 7 * 13?" → "91" — full Codex round-trip in ~24 s including cold load.

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

## Talk to your local model through WeChat (公众号 sandbox)

You can wire any of the local models behind a real WeChat 公众号 sandbox in ~10 min. Architecture:

```
WeChat user ─► WeChat servers ─► cloudflared tunnel ─► localhost:8080
                                                            │
                                                ACK in <5s  │
                                                            ▼
                                         FastAPI (llm-wechat)
                                                            │
                                                            ▼
                                             Background: LLMClient → Hermes 3
                                                            │
                                                            ▼
                                          客服消息 API → user
```

Why "ACK + push" instead of synchronous reply: WeChat requires servers to respond within **5 seconds**, but Hermes 3 averages ~12 s and DeepSeek-R1 over 60 s. We send an instant ACK ("正在思考…") and then push the real answer via 客服消息 (custom service message) once the LLM finishes. Retries are dedupe'd by MsgId.

### Setup (one-time)

1. **Get a sandbox account.** Open <https://mp.weixin.qq.com/debug/cgi-bin/sandbox?t=sandbox/login>, scan with personal WeChat. You'll get `appID` + `appsecret`.
2. **Install cloudflared** (free, no account, gives you a public HTTPS URL):

   ```bash
   brew install cloudflared
   ```

3. **Start the bridge:**

   ```bash
   export WECHAT_TOKEN="any_string_you_pick_min_3_chars"
   export WECHAT_APPID="<the appID from sandbox>"
   export WECHAT_APPSECRET="<the appsecret from sandbox>"
   uv run llm-wechat --port 8080 --model hermes3:8b
   ```

4. **In a second terminal, open a tunnel:**

   ```bash
   cloudflared tunnel --url http://localhost:8080
   ```

   It prints a line like `Your quick Tunnel has been created! https://random-words.trycloudflare.com`.

5. **Wire up the sandbox.** Back in the sandbox page, paste:

   - **URL:** `https://random-words.trycloudflare.com/wechat`
   - **Token:** the same `WECHAT_TOKEN` you exported above

   Click **提交**. If everything's right you get "配置成功".

6. **Follow the sandbox QR code** with your personal WeChat (you can have up to ~100 testers), then just chat with the test account. Your local Hermes 3 will reply.

Sanity-check the server is alive without WeChat:

```bash
curl http://localhost:8080/                # should return service JSON
```

### Live-verified end-to-end (June 21, 2026)

Took ~30 min of trial-and-error to get the loop running through a free public tunnel.
The actual happy path, once everything is configured:

```
WeChat user "Rachel" → 测试公众号 → Tencent → cloudflared tunnel → llm-wechat
                                                                       │
                                              ACK in <2 s ←────────────┤
                                                                       ▼
                                                          Hermes 3 (8B, local) ~6 s
                                                                       │
                                                                       ▼
                                                          WeChat 客服消息 API
                                                                       │
WeChat user "Rachel" ← 测试公众号 ← Tencent ← ─────────────────────────┘

# Server logs from the real run:
# 19:36:32  POST from 162.62.81.123 (Tencent) — openid=orLS_2O85...
# 19:36:36  Ollama 200 OK (Hermes finished)
# 19:36:38  api.weixin.qq.com/cgi-bin/message/custom/send → HTTP 200 ✓
```

In the WeChat client, Rachel saw:

> 🤔 收到,正在用本地模型推理,稍等几秒钟…
>
> Rachel, 我是一个 AI 助手, 名字是 Elsa. (etc.)

(Hermes 3 cheekily named itself "Elsa" — we never told it that.)

### Lessons learned the hard way

- **Free tunnels expire when the laptop sleeps.** Each cloudflared/ngrok/lhr.life session generates a new random subdomain. For anything beyond a one-off demo, set up a Cloudflare Named Tunnel (free, persistent) or a paid ngrok plan.
- **ngrok's free tier serves a browser-warning interstitial** for browser-like User-Agents, which breaks WeChat's verification request. localhost.run and trycloudflare don't have this problem.
- **Refresh the sandbox QR follower if the loop appears silent.** WeChat 测试号 silently drops messages for non-followers; an expired follower state will mimic a network failure exactly. (We spent ~1 hour blaming Tencent's "anti-abuse blacklist" before realizing this; turned out to be wrong.)
- **5-second ACK + background push is mandatory** for any local-LLM-backed WeChat bot, since even a 4-bit 8B model on Apple Silicon averages ~12 s.

### Limitations of the sandbox

- Up to ~100 test followers (QR-code-added)
- Replies go through 客服消息 API, which expects users to have messaged you in the last 48 h (always true in a chat session)
- Sandbox accounts cannot host menus or publish broadcasts — for that you need a verified subscription account

## Roadmap

- [x] Phase 1: DeepSeek-R1 + Hermes 3 local, unified client, examples
- [x] Phase 1.5: wire OpenAI's `codex` CLI to local Hermes 3 (so the same agent UX runs offline / free)
- [x] Phase 1.75: real benchmarks against 3 local models, results in [`benchmarks/REPORT.md`](benchmarks/REPORT.md)
- [x] Phase 1.9: WeChat 公众号 bridge (`llm-wechat`) — _live-verified end-to-end on June 21, 2026_
- [ ] Phase 2: add Xiaomi MiMo UltraSpeed (cloud) once trial access is approved (apply at [platform.xiaomimimo.com/ultraspeed](https://platform.xiaomimimo.com/ultraspeed); trial window June 9–23, 2026), compare 1000 tps claim against local 14B
- [ ] Phase 3: optional Next.js front-end matching `data-copilot` style

## Wiring MiMo in (when the approval email arrives)

The config registry already has two MiMo entries pre-wired:

- `mimo/v2.5-pro` — pay-as-you-go, anyone with a MiMo account can use it now
- `mimo/ultraspeed` — beta only, gated by application + email approval

To activate either one:

```bash
# 1. Drop your MiMo API key into .env (no MIMO_BASE_URL needed unless on Token Plan)
echo 'MIMO_API_KEY=sk-...' >> .env

# 2. Smoke-test the connection
uv run llm-chat --model mimo/v2.5-pro "Hello, who are you?"

# 3. Run the benchmark suite against MiMo + the three local models
uv run llm-bench --models hermes3:8b,gpt-oss:20b,mimo/v2.5-pro --out benchmarks/results-with-mimo.json
```

The model name `mimo-v2.5-pro-ultraspeed` in the registry is a placeholder from
the MiMo blog post; the approval email may give a slightly different model ID.
If a 400 comes back, the only edit needed is the `model_id` line in `config.py`.

## Why this project exists

I wanted one place to:

1. Confirm DeepSeek-R1 and Hermes 3 actually run usably on my M4 / 24 GB Mac
2. Have a real, working "what does an OpenAI-compatible API look like" reference
3. Test MiMo UltraSpeed against a local baseline as soon as the trial activates
4. Reuse the same code to wire LLMs into other tools (Codex, WeChat bots, etc.)

If any of that is useful to you, feel free to fork.

## License

MIT
