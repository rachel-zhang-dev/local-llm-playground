"""Compare multiple models on the same prompt: latency, throughput, output."""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from local_llm_playground.client import ChatMessage, ChatResponse, LLMClient
from local_llm_playground.config import MODELS
from local_llm_playground.utils import split_reasoning

console = Console()
app = typer.Typer(add_completion=False, help="Benchmark multiple models on a prompt.")


@dataclass
class BenchResult:
    model: str
    prompt: str
    elapsed_seconds: float
    prompt_tokens: int
    completion_tokens: int
    throughput: float
    answer: str
    reasoning: str
    error: str | None = None


def run_one(model: str, prompt: str, *, temperature: float = 0.0) -> BenchResult:
    try:
        client = LLMClient(model)
        resp: ChatResponse = client.chat(
            [ChatMessage("user", prompt)], temperature=temperature
        )
    except Exception as exc:
        return BenchResult(
            model=model,
            prompt=prompt,
            elapsed_seconds=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            throughput=0.0,
            answer="",
            reasoning="",
            error=str(exc),
        )

    parts = split_reasoning(resp.content)
    return BenchResult(
        model=model,
        prompt=prompt,
        elapsed_seconds=resp.elapsed_seconds,
        prompt_tokens=resp.usage.prompt_tokens,
        completion_tokens=resp.usage.completion_tokens,
        throughput=resp.throughput,
        answer=parts.answer,
        reasoning=parts.reasoning,
    )


def render_results(results: list[BenchResult], preview_chars: int = 200) -> Table:
    table = Table(title="Benchmark results", show_lines=True)
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("Latency", justify="right")
    table.add_column("Out tokens", justify="right")
    table.add_column("Throughput", justify="right", style="green")
    table.add_column("Answer preview")
    for r in results:
        if r.error:
            table.add_row(r.model, "—", "—", "—", f"[red]error: {r.error}[/red]")
            continue
        preview = r.answer[:preview_chars]
        if len(r.answer) > preview_chars:
            preview += "..."
        table.add_row(
            r.model,
            f"{r.elapsed_seconds:.2f}s",
            str(r.completion_tokens),
            f"{r.throughput:.1f} tok/s",
            preview,
        )
    return table


@app.command()
def main(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Prompt to test"),
    models: str = typer.Option(
        "deepseek-r1:14b,hermes3:8b",
        "--models",
        "-m",
        help="Comma-separated model names",
    ),
    temperature: float = typer.Option(0.0, "--temperature", "-t"),
    runs: int = typer.Option(1, "--runs", "-r", help="Runs per model"),
    output: Path | None = typer.Option(None, "--output", "-o", help="JSON output file"),
    show_reasoning: bool = typer.Option(
        False, "--reasoning", help="Print reasoning trace too"
    ),
) -> None:
    """Run the same prompt through several models and compare."""
    model_list = [m.strip() for m in models.split(",") if m.strip()]
    for m in model_list:
        if m not in MODELS:
            console.print(f"[red]unknown model:[/red] {m}")
            raise typer.Exit(code=1)

    all_results: list[BenchResult] = []
    for model in model_list:
        for i in range(runs):
            label = f"{model}" if runs == 1 else f"{model} (run {i + 1}/{runs})"
            with console.status(f"running [bold]{label}[/bold]..."):
                result = run_one(model, prompt, temperature=temperature)
            all_results.append(result)
            if result.error:
                console.print(f"[red]{model}: {result.error}[/red]")
            else:
                console.print(
                    f"[green]{label}[/green]: "
                    f"{result.elapsed_seconds:.2f}s, "
                    f"{result.throughput:.1f} tok/s"
                )

    console.print()
    console.print(render_results(all_results))

    if runs > 1:
        console.print("\n[bold]Average throughput per model:[/bold]")
        for model in model_list:
            tps = [r.throughput for r in all_results if r.model == model and not r.error]
            if tps:
                console.print(
                    f"  {model}: mean={statistics.mean(tps):.1f} tok/s, "
                    f"stdev={statistics.stdev(tps) if len(tps) > 1 else 0:.1f}"
                )

    if show_reasoning:
        for r in all_results:
            if r.reasoning:
                console.print(f"\n[dim]{r.model} reasoning:[/dim]")
                console.print(r.reasoning)

    if output:
        output.write_text(
            json.dumps([asdict(r) for r in all_results], indent=2, ensure_ascii=False)
        )
        console.print(f"\n[dim]results saved to {output}[/dim]")


if __name__ == "__main__":
    app()
