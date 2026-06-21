"""Unified client that hides the Ollama vs OpenAI-compatible difference."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

from ollama import Client as OllamaClient
from openai import OpenAI

from local_llm_playground.config import ModelConfig, Provider, get_model

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ChatMessage:
    role: Role
    content: str


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class ChatResponse:
    content: str
    model: str
    elapsed_seconds: float
    usage: Usage = field(default_factory=Usage)
    raw: Any = None

    @property
    def throughput(self) -> float:
        """Output tokens per second (0.0 if no usage info)."""
        if self.elapsed_seconds <= 0 or self.usage.completion_tokens == 0:
            return 0.0
        return self.usage.completion_tokens / self.elapsed_seconds


@dataclass
class StreamChunk:
    delta: str
    done: bool = False
    usage: Usage | None = None


class LLMClient:
    """Talk to any model in our registry with a single API.

    Examples:
        client = LLMClient("deepseek-r1:14b")
        resp = client.chat([ChatMessage("user", "hi")])
        print(resp.content, resp.throughput)
    """

    def __init__(self, model: str | ModelConfig | None = None) -> None:
        cfg = model if isinstance(model, ModelConfig) else get_model(model)
        self.config: ModelConfig = cfg

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Send a chat request and wait for the full response."""
        if self.config.provider is Provider.OLLAMA:
            return self._chat_ollama(messages, temperature, max_tokens, **kwargs)
        return self._chat_openai(messages, temperature, max_tokens, **kwargs)

    def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        """Stream chunks of the response as they arrive."""
        if self.config.provider is Provider.OLLAMA:
            yield from self._stream_ollama(messages, temperature, max_tokens, **kwargs)
        else:
            yield from self._stream_openai(messages, temperature, max_tokens, **kwargs)

    def _chat_ollama(
        self,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int | None,
        **kwargs: Any,
    ) -> ChatResponse:
        client = OllamaClient(host=self.config.base_url)
        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        t0 = time.perf_counter()
        resp = client.chat(
            model=self.config.model_id,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            options=options,
            **kwargs,
        )
        elapsed = time.perf_counter() - t0

        return ChatResponse(
            content=resp["message"]["content"],
            model=self.config.name,
            elapsed_seconds=elapsed,
            usage=Usage(
                prompt_tokens=resp.get("prompt_eval_count", 0),
                completion_tokens=resp.get("eval_count", 0),
            ),
            raw=resp,
        )

    def _stream_ollama(
        self,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int | None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        client = OllamaClient(host=self.config.base_url)
        options: dict[str, Any] = {"temperature": temperature}
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        stream = client.chat(
            model=self.config.model_id,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            options=options,
            stream=True,
            **kwargs,
        )
        for chunk in stream:
            delta = chunk.get("message", {}).get("content", "")
            done = bool(chunk.get("done"))
            usage = None
            if done:
                usage = Usage(
                    prompt_tokens=chunk.get("prompt_eval_count", 0),
                    completion_tokens=chunk.get("eval_count", 0),
                )
            yield StreamChunk(delta=delta, done=done, usage=usage)

    def _make_openai_client(self) -> OpenAI:
        api_key = self.config.api_key or "sk-not-needed"
        return OpenAI(base_url=self.config.base_url, api_key=api_key)

    def _chat_openai(
        self,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int | None,
        **kwargs: Any,
    ) -> ChatResponse:
        client = self._make_openai_client()
        t0 = time.perf_counter()
        resp = client.chat.completions.create(
            model=self.config.model_id,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        elapsed = time.perf_counter() - t0

        usage_obj = resp.usage
        return ChatResponse(
            content=resp.choices[0].message.content or "",
            model=self.config.name,
            elapsed_seconds=elapsed,
            usage=Usage(
                prompt_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
            ),
            raw=resp,
        )

    def _stream_openai(
        self,
        messages: list[ChatMessage],
        temperature: float,
        max_tokens: int | None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        client = self._make_openai_client()
        stream = client.chat.completions.create(
            model=self.config.model_id,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )
        for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if not choice:
                continue
            delta = choice.delta.content or ""
            done = choice.finish_reason is not None
            usage = None
            if done and getattr(chunk, "usage", None):
                usage = Usage(
                    prompt_tokens=chunk.usage.prompt_tokens or 0,
                    completion_tokens=chunk.usage.completion_tokens or 0,
                )
            yield StreamChunk(delta=delta, done=done, usage=usage)
