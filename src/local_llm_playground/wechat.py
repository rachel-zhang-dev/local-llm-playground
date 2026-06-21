"""Minimal WeChat Official Account (公众号) bridge: WeChat → local LLM.

How the loop works (sandbox / 公众号 测试号):

    WeChat user ─► WeChat server ─► POST /wechat (XML body)
                                       │
                                       │ 1) verify signature
                                       │ 2) ACK in <5s with "稍等"
                                       │ 3) schedule background LLM call
                                       ▼
                                  LLMClient(model) ─► answer
                                       │
                                       ▼ 4) push answer via 客服消息 API
                                  WeChat server ─► user

The 5-second ACK rule is critical: WeChat retries up to 3× if we don't
respond in time. We dedupe by MsgId so retries don't trigger duplicate
LLM calls.

Run with:
    uv run llm-wechat \
        --token YOUR_TOKEN_FROM_SANDBOX \
        --appid YOUR_APPID \
        --secret YOUR_APPSECRET \
        --model hermes3:8b \
        --port 8080

Then expose port 8080 with cloudflared and paste the https URL into the
sandbox's "URL" field (with the matching token).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import httpx
import typer
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response

from .client import ChatMessage, LLMClient

log = logging.getLogger("local_llm_playground.wechat")

cli = typer.Typer(add_completion=False, no_args_is_help=False)


@dataclass
class WeChatConfig:
    token: str
    appid: str
    appsecret: str
    model: str = "hermes3:8b"
    max_tokens: int = 600
    system_prompt: str = (
        "You are a helpful assistant. Reply in the same language as the user. "
        "Keep replies short (under 200 words) so they read well on WeChat."
    )


# Process-wide state. Single-worker uvicorn is assumed.
_seen_msg_ids: set[str] = set()
_pending_lock: asyncio.Lock | None = None  # lazily created on first use


def _verify_signature(token: str, timestamp: str, nonce: str, signature: str) -> bool:
    items = sorted([token, timestamp, nonce])
    digest = hashlib.sha1("".join(items).encode("utf-8")).hexdigest()
    return digest == signature


def _parse_message(body: bytes) -> dict[str, str]:
    root = ET.fromstring(body)
    return {child.tag: (child.text or "") for child in root}


def _xml_reply(to_user: str, from_user: str, content: str) -> str:
    return (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        f"<CreateTime>{int(time.time())}</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        "</xml>"
    )


class TokenCache:
    """Cache for WeChat's access_token (valid ~2h, we refresh at 90 min)."""

    def __init__(self, appid: str, secret: str) -> None:
        self.appid = appid
        self.secret = secret
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._expires_at:
                return self._token
            url = "https://api.weixin.qq.com/cgi-bin/token"
            params = {
                "grant_type": "client_credential",
                "appid": self.appid,
                "secret": self.secret,
            }
            async with httpx.AsyncClient(timeout=10) as cli_http:
                resp = await cli_http.get(url, params=params)
            data = resp.json()
            if "access_token" not in data:
                raise RuntimeError(f"WeChat token fetch failed: {data}")
            self._token = data["access_token"]
            # Refresh 10 min before expiry
            self._expires_at = time.time() + int(data.get("expires_in", 7200)) - 600
            return self._token


async def _send_kefu_text(token_cache: TokenCache, openid: str, text: str) -> None:
    """Push a text message to a WeChat user via 客服消息 API."""
    access_token = await token_cache.get()
    url = "https://api.weixin.qq.com/cgi-bin/message/custom/send"
    payload: dict[str, Any] = {
        "touser": openid,
        "msgtype": "text",
        "text": {"content": text},
    }
    async with httpx.AsyncClient(timeout=10) as cli_http:
        resp = await cli_http.post(url, params={"access_token": access_token}, json=payload)
    result = resp.json()
    if result.get("errcode", 0) != 0:
        log.warning("kefu send failed: %s", result)


def _run_llm(model: str, system_prompt: str, user_text: str, max_tokens: int) -> str:
    """Run the LLM synchronously and return the cleaned answer."""
    from .utils import split_reasoning

    client = LLMClient(model)
    resp = client.chat(
        [
            ChatMessage("system", system_prompt),
            ChatMessage("user", user_text),
        ],
        temperature=0.7,
        max_tokens=max_tokens,
    )
    parts = split_reasoning(resp.content)
    answer = (parts.answer or resp.content or "").strip()
    return answer or "(空回复,模型还在思考)"


async def _llm_and_push(cfg: WeChatConfig, token_cache: TokenCache, openid: str, user_text: str) -> None:
    """Background task: call LLM, push reply via 客服消息. Never raises."""
    loop = asyncio.get_running_loop()
    try:
        answer = await loop.run_in_executor(
            None,
            _run_llm,
            cfg.model,
            cfg.system_prompt,
            user_text,
            cfg.max_tokens,
        )
    except Exception as exc:
        log.exception("LLM call failed for openid=%s", openid)
        answer = f"模型出错了: {exc}"
    try:
        await _send_kefu_text(token_cache, openid, answer)
    except Exception:
        # Background tasks must not raise — they have no caller to handle them.
        log.exception("kefu push failed for openid=%s (answer was: %s)", openid, answer[:80])


def build_app(cfg: WeChatConfig) -> FastAPI:
    app = FastAPI(title="local-llm-playground · WeChat bridge")
    token_cache = TokenCache(cfg.appid, cfg.appsecret)

    @app.get("/wechat")
    async def verify(
        signature: str = "",
        timestamp: str = "",
        nonce: str = "",
        echostr: str = "",
    ) -> Response:
        if not _verify_signature(cfg.token, timestamp, nonce, signature):
            raise HTTPException(status_code=403, detail="bad signature")
        return Response(content=echostr, media_type="text/plain")

    @app.post("/wechat")
    async def handle(request: Request, background: BackgroundTasks) -> Response:
        signature = request.query_params.get("signature", "")
        timestamp = request.query_params.get("timestamp", "")
        nonce = request.query_params.get("nonce", "")
        if not _verify_signature(cfg.token, timestamp, nonce, signature):
            raise HTTPException(status_code=403, detail="bad signature")

        body = await request.body()
        try:
            msg = _parse_message(body)
        except ET.ParseError:
            return Response(content="", media_type="application/xml")

        msg_type = msg.get("MsgType", "")
        from_user = msg.get("FromUserName", "")
        to_user = msg.get("ToUserName", "")
        msg_id = msg.get("MsgId", "")
        content = msg.get("Content", "").strip()

        # Deduplicate WeChat's 3-retries-on-timeout
        if msg_id and msg_id in _seen_msg_ids:
            return Response(content="", media_type="application/xml")
        if msg_id:
            _seen_msg_ids.add(msg_id)

        if msg_type == "event" and msg.get("Event") == "subscribe":
            reply = (
                "欢迎!这是一个对接本地 LLM 的演示。"
                "直接给我发消息,我会调用本地 Hermes 3 回答你。"
                "因为是本地推理,首次回答可能需要 10-30 秒。"
            )
            return Response(
                content=_xml_reply(from_user, to_user, reply),
                media_type="application/xml",
            )

        if msg_type != "text" or not content:
            return Response(
                content=_xml_reply(from_user, to_user, "只支持纯文本消息哦。"),
                media_type="application/xml",
            )

        background.add_task(_llm_and_push, cfg, token_cache, from_user, content)
        ack = "🤔 收到,正在用本地模型推理,稍等几秒钟…"
        return Response(
            content=_xml_reply(from_user, to_user, ack),
            media_type="application/xml",
        )

    @app.get("/")
    async def root() -> dict[str, Any]:
        return {
            "service": "local-llm-playground · WeChat bridge",
            "model": cfg.model,
            "callback": "/wechat",
        }

    return app


@cli.command()
def serve(
    token: str = typer.Option(..., envvar="WECHAT_TOKEN", help="Sandbox token"),
    appid: str = typer.Option(..., envvar="WECHAT_APPID", help="appID from sandbox"),
    secret: str = typer.Option(..., envvar="WECHAT_APPSECRET", help="appsecret"),
    model: str = typer.Option("hermes3:8b", help="Model name in MODELS registry"),
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8080, help="Bind port"),
    max_tokens: int = typer.Option(600, help="Max tokens per reply"),
) -> None:
    """Run the WeChat bridge server.

    Then in another terminal:

        cloudflared tunnel --url http://localhost:8080

    Paste the https://*.trycloudflare.com URL + /wechat into the sandbox
    URL field, set the token to match, and click "提交".
    """
    cfg = WeChatConfig(
        token=token,
        appid=appid,
        appsecret=secret,
        model=model,
        max_tokens=max_tokens,
    )
    app = build_app(cfg)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    log.info("starting WeChat bridge on %s:%d → model=%s", host, port, model)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":  # pragma: no cover
    cli()


# Avoid unused-import warning when running as a script
_ = os  # for future env-driven config
