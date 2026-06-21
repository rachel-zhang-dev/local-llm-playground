"""OpenAI-compatible FastAPI server backed by any model in the registry.

This lets you point tools that expect an OpenAI API (Codex, chatgpt-on-wechat,
LobeChat, etc.) at your local Ollama models. Run with:

    uv run llm-serve --model deepseek-r1:14b

Then use base_url=http://localhost:8080/v1 in the client tool.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Literal

import typer
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from local_llm_playground.client import ChatMessage, LLMClient
from local_llm_playground.config import DEFAULT_MODEL, MODELS


class OpenAIMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[OpenAIMessage]
    temperature: float = 0.7
    max_tokens: int | None = None
    stream: bool = False


class ChatCompletionChoice(BaseModel):
    index: int = 0
    message: OpenAIMessage
    finish_reason: str = "stop"


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:24]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str
    choices: list[ChatCompletionChoice]
    usage: ChatCompletionUsage


def build_app(default_model: str) -> FastAPI:
    app = FastAPI(title="local-llm-playground", version="0.1.0")

    @app.get("/v1/models")
    def list_models() -> dict:
        return {
            "object": "list",
            "data": [
                {
                    "id": name,
                    "object": "model",
                    "owned_by": cfg.provider.value,
                }
                for name, cfg in MODELS.items()
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(req: ChatCompletionRequest):
        model_name = req.model if req.model in MODELS else default_model
        if model_name not in MODELS:
            raise HTTPException(status_code=404, detail=f"unknown model: {req.model}")

        client = LLMClient(model_name)
        messages = [ChatMessage(role=m.role, content=m.content) for m in req.messages]

        if not req.stream:
            resp = client.chat(
                messages, temperature=req.temperature, max_tokens=req.max_tokens
            )
            return ChatCompletionResponse(
                model=model_name,
                choices=[
                    ChatCompletionChoice(
                        message=OpenAIMessage(role="assistant", content=resp.content)
                    )
                ],
                usage=ChatCompletionUsage(
                    prompt_tokens=resp.usage.prompt_tokens,
                    completion_tokens=resp.usage.completion_tokens,
                    total_tokens=resp.usage.total_tokens,
                ),
            )

        async def stream() -> AsyncIterator[bytes]:
            chunk_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
            created = int(time.time())
            for chunk in client.chat_stream(
                messages, temperature=req.temperature, max_tokens=req.max_tokens
            ):
                payload = {
                    "id": chunk_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model_name,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": chunk.delta},
                            "finish_reason": "stop" if chunk.done else None,
                        }
                    ],
                }
                yield f"data: {json.dumps(payload)}\n\n".encode()
            yield b"data: [DONE]\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


cli = typer.Typer(add_completion=False, help="Serve any local model as an OpenAI API.")


@cli.command()
def main(
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Default model"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start the OpenAI-compatible server."""
    if model not in MODELS:
        raise typer.BadParameter(f"unknown model: {model}")
    app = build_app(model)
    uvicorn.run(app, host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()
