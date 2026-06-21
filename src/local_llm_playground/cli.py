"""Interactive chat REPL for any model in the registry."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from local_llm_playground.client import ChatMessage, LLMClient
from local_llm_playground.config import DEFAULT_MODEL, MODELS
from local_llm_playground.utils import split_reasoning

app = typer.Typer(add_completion=False, help="Chat with any local or cloud model.")
console = Console()

COMMANDS_HELP = """\
Slash commands:
  /model <name>   switch model (e.g. /model hermes3:8b)
  /models         list available models
  /system <text>  set/replace system prompt
  /reset          clear conversation history
  /stream         toggle streaming mode
  /reasoning      toggle showing <think> reasoning trace
  /help           show this help
  /quit           exit (Ctrl+D also works)
"""


def render_models_table() -> Table:
    table = Table(title="Models in registry", show_lines=False)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Provider", style="magenta")
    table.add_column("Description")
    for name, cfg in MODELS.items():
        table.add_row(name, cfg.provider.value, cfg.description)
    return table


def chat_once_streaming(
    client: LLMClient, history: list[ChatMessage], *, show_reasoning: bool
) -> str:
    """Send one round, streaming tokens with rich Live."""
    full_text = ""
    last_usage = None
    with Live(console=console, refresh_per_second=20) as live:
        for chunk in client.chat_stream(history):
            full_text += chunk.delta
            live.update(Markdown(full_text or "_thinking..._"))
            if chunk.done:
                last_usage = chunk.usage

    if show_reasoning:
        parts = split_reasoning(full_text)
        if parts.reasoning:
            console.print(
                Panel(parts.reasoning, title="reasoning trace", border_style="dim")
            )
    if last_usage and last_usage.completion_tokens:
        console.print(
            f"[dim]({last_usage.completion_tokens} tokens out, "
            f"{last_usage.prompt_tokens} in)[/dim]"
        )
    return full_text


def chat_once_blocking(
    client: LLMClient, history: list[ChatMessage], *, show_reasoning: bool
) -> str:
    """Send one round, wait for full response, print at end."""
    with console.status("[bold cyan]thinking...[/bold cyan]"):
        resp = client.chat(history)
    text = resp.content
    if show_reasoning:
        parts = split_reasoning(text)
        if parts.reasoning:
            console.print(
                Panel(parts.reasoning, title="reasoning trace", border_style="dim")
            )
        console.print(Markdown(parts.answer or text))
    else:
        console.print(Markdown(text))
    console.print(
        f"[dim]({resp.usage.completion_tokens} tokens out in "
        f"{resp.elapsed_seconds:.2f}s = {resp.throughput:.1f} tok/s)[/dim]"
    )
    return text


@app.command()
def main(
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Initial model"),
    system: str | None = typer.Option(None, "--system", "-s", help="System prompt"),
    no_stream: bool = typer.Option(False, "--no-stream", help="Disable streaming"),
    show_reasoning: bool = typer.Option(
        True, "--reasoning/--no-reasoning", help="Show <think> trace if present"
    ),
) -> None:
    """Start an interactive chat session."""
    if model not in MODELS:
        console.print(f"[red]Unknown model:[/red] {model}")
        console.print(render_models_table())
        raise typer.Exit(code=1)

    client = LLMClient(model)
    history: list[ChatMessage] = []
    if system:
        history.append(ChatMessage("system", system))

    streaming = not no_stream

    console.print(
        Panel.fit(
            f"[bold cyan]{client.config.name}[/bold cyan]\n"
            f"[dim]{client.config.description}[/dim]\n\n"
            f"streaming: {streaming} · reasoning: {show_reasoning}\n"
            "type /help for commands, /quit to exit",
            title="local-llm-playground",
        )
    )

    while True:
        try:
            user_input = console.input("\n[bold green]you ›[/bold green] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nbye.")
            return

        if not user_input:
            continue

        if user_input.startswith("/"):
            cmd, _, arg = user_input.partition(" ")
            cmd = cmd.lower()
            arg = arg.strip()
            if cmd in ("/quit", "/exit"):
                return
            if cmd == "/help":
                console.print(COMMANDS_HELP)
                continue
            if cmd == "/models":
                console.print(render_models_table())
                continue
            if cmd == "/model":
                if arg not in MODELS:
                    console.print(f"[red]unknown model:[/red] {arg}")
                    continue
                client = LLMClient(arg)
                console.print(f"[cyan]switched to {arg}[/cyan]")
                continue
            if cmd == "/system":
                history = [m for m in history if m.role != "system"]
                if arg:
                    history.insert(0, ChatMessage("system", arg))
                    console.print(f"[cyan]system prompt set ({len(arg)} chars)[/cyan]")
                else:
                    console.print("[cyan]system prompt cleared[/cyan]")
                continue
            if cmd == "/reset":
                system_msgs = [m for m in history if m.role == "system"]
                history = system_msgs
                console.print("[cyan]history cleared[/cyan]")
                continue
            if cmd == "/stream":
                streaming = not streaming
                console.print(f"[cyan]streaming: {streaming}[/cyan]")
                continue
            if cmd == "/reasoning":
                show_reasoning = not show_reasoning
                console.print(f"[cyan]show reasoning: {show_reasoning}[/cyan]")
                continue
            console.print(f"[red]unknown command:[/red] {cmd}")
            continue

        history.append(ChatMessage("user", user_input))
        console.print(f"\n[bold cyan]{client.config.name} ›[/bold cyan]")

        try:
            if streaming:
                answer = chat_once_streaming(
                    client, history, show_reasoning=show_reasoning
                )
            else:
                answer = chat_once_blocking(
                    client, history, show_reasoning=show_reasoning
                )
        except Exception as exc:
            console.print(f"[red]error:[/red] {exc}")
            history.pop()
            continue

        history.append(ChatMessage("assistant", answer))


if __name__ == "__main__":
    app()
