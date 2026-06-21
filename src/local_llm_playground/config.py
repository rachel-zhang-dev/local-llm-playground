"""Model registry and runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from dotenv import load_dotenv

load_dotenv()


def _ensure_localhost_bypasses_proxy() -> None:
    """Make sure HTTP clients (httpx, requests, ollama) don't try to send
    localhost / 127.0.0.1 traffic through a system proxy.

    On macOS the user may have a global HTTP proxy enabled (Clash, Surge, ...).
    httpx auto-picks that up via env, which breaks talking to local Ollama.
    """
    extras = {"localhost", "127.0.0.1", "::1"}
    for var in ("NO_PROXY", "no_proxy"):
        current = {h.strip() for h in os.environ.get(var, "").split(",") if h.strip()}
        os.environ[var] = ",".join(sorted(current | extras))


_ensure_localhost_bypasses_proxy()


class Provider(StrEnum):
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"


@dataclass(frozen=True)
class ModelConfig:
    """Registry entry for a model we know how to talk to."""

    name: str
    provider: Provider
    model_id: str
    base_url: str
    api_key_env: str | None = None
    supports_reasoning: bool = False
    description: str = ""

    @property
    def api_key(self) -> str | None:
        if not self.api_key_env:
            return None
        return os.getenv(self.api_key_env)


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


MODELS: dict[str, ModelConfig] = {
    "deepseek-r1:14b": ModelConfig(
        name="deepseek-r1:14b",
        provider=Provider.OLLAMA,
        model_id="deepseek-r1:14b",
        base_url=OLLAMA_HOST,
        supports_reasoning=True,
        description="DeepSeek-R1 14B (distilled). Strong reasoning, runs locally on Apple Silicon.",
    ),
    "hermes3:8b": ModelConfig(
        name="hermes3:8b",
        provider=Provider.OLLAMA,
        model_id="hermes3:8b",
        base_url=OLLAMA_HOST,
        description="NousResearch Hermes 3 8B. Good instruction following and agent behavior.",
    ),
    "gpt-oss:20b": ModelConfig(
        name="gpt-oss:20b",
        provider=Provider.OLLAMA,
        model_id="gpt-oss:20b",
        base_url=OLLAMA_HOST,
        supports_reasoning=True,
        description="OpenAI gpt-oss 20B (open weights). Reasoning model, fast on M-series.",
    ),
    "openai/gpt-5.5": ModelConfig(
        name="openai/gpt-5.5",
        provider=Provider.OPENAI_COMPATIBLE,
        model_id="gpt-5.5",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        description="OpenAI GPT-5.5 via official API. Requires OPENAI_API_KEY.",
    ),
    # Xiaomi MiMo — OpenAI-compatible, see https://platform.xiaomimimo.com/docs/en-US/api/chat/openai-api
    # The MiMo API uses `max_completion_tokens` (not `max_tokens`); the OpenAI Python
    # SDK 1.x accepts either, so we don't special-case it. If you start seeing
    # 400s mentioning `max_tokens` from MiMo, swap that parameter name in client.py.
    "mimo/v2.5-pro": ModelConfig(
        name="mimo/v2.5-pro",
        provider=Provider.OPENAI_COMPATIBLE,
        model_id="mimo-v2.5-pro",
        base_url=os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
        api_key_env="MIMO_API_KEY",
        description="Xiaomi MiMo V2.5-Pro (pay-as-you-go). Open to anyone with a MiMo API key.",
    ),
    # UltraSpeed beta — same model, 10x faster inference. Application required at
    # https://platform.xiaomimimo.com/ultraspeed (trial window: Jun 9–23, 2026).
    # The exact `model_id` will be confirmed in the approval email; the placeholder
    # below is the name used in the MiMo blog post.
    "mimo/ultraspeed": ModelConfig(
        name="mimo/ultraspeed",
        provider=Provider.OPENAI_COMPATIBLE,
        model_id="mimo-v2.5-pro-ultraspeed",
        base_url=os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1"),
        api_key_env="MIMO_API_KEY",
        description="Xiaomi MiMo UltraSpeed (1T params, 1000+ tps). Beta-only; requires MIMO_API_KEY.",
    ),
}


DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "deepseek-r1:14b")


def get_model(name: str | None = None) -> ModelConfig:
    """Lookup a model config by name. Raises KeyError if not found."""
    key = name or DEFAULT_MODEL
    if key not in MODELS:
        available = ", ".join(MODELS.keys())
        raise KeyError(f"Unknown model: {key!r}. Available: {available}")
    return MODELS[key]
