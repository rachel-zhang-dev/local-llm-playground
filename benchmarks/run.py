"""Run the full benchmark suite and generate a JSON dump + Markdown report.

Usage:
    uv run python benchmarks/run.py
    uv run python benchmarks/run.py --models deepseek-r1:14b,hermes3:8b
    uv run python benchmarks/run.py --prompts logic-snail,bug-find

Outputs:
    benchmarks/results.json
    benchmarks/REPORT.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from local_llm_playground import ChatMessage, LLMClient
from local_llm_playground.utils import split_reasoning

BENCH_DIR = Path(__file__).resolve().parent
DEFAULT_MODELS = ["deepseek-r1:14b", "hermes3:8b", "gpt-oss:20b"]

console = Console()


@dataclass
class Prompt:
    id: str
    category: str
    description: str
    text: str
    max_tokens: int = 500


@dataclass
class RunResult:
    prompt_id: str
    category: str
    model: str
    elapsed_seconds: float
    prompt_tokens: int
    completion_tokens: int
    throughput: float
    answer: str
    reasoning: str = ""
    error: str | None = None


def load_prompts(path: Path) -> list[Prompt]:
    raw = tomllib.loads(path.read_text())
    return [Prompt(**p) for p in raw["prompts"]]


def run_single(model: str, prompt: Prompt) -> RunResult:
    try:
        client = LLMClient(model)
        resp = client.chat(
            [ChatMessage("user", prompt.text.strip())],
            temperature=0.0,
            max_tokens=prompt.max_tokens,
        )
    except Exception as exc:
        return RunResult(
            prompt_id=prompt.id,
            category=prompt.category,
            model=model,
            elapsed_seconds=0.0,
            prompt_tokens=0,
            completion_tokens=0,
            throughput=0.0,
            answer="",
            error=str(exc),
        )

    parts = split_reasoning(resp.content)
    return RunResult(
        prompt_id=prompt.id,
        category=prompt.category,
        model=model,
        elapsed_seconds=resp.elapsed_seconds,
        prompt_tokens=resp.usage.prompt_tokens,
        completion_tokens=resp.usage.completion_tokens,
        throughput=resp.throughput,
        answer=parts.answer,
        reasoning=parts.reasoning,
    )


def render_report(results: list[RunResult], prompts: list[Prompt], models: list[str]) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = [
        "# Benchmark Report",
        "",
        f"_Generated {now} · MacBook Pro M4 · 24 GB unified memory · macOS Sequoia · "
        f"Ollama 0.24.0 · temperature=0_",
        "",
    ]

    # Summary table: avg throughput + avg latency per model
    lines += [
        "## Summary by model",
        "",
        "| Model | Avg throughput | Avg latency | Avg out tokens | Errors |",
        "|---|---|---|---|---|",
    ]
    for model in models:
        rows = [r for r in results if r.model == model]
        ok_rows = [r for r in rows if not r.error]
        errors = sum(1 for r in rows if r.error)
        if not ok_rows:
            lines.append(f"| `{model}` | — | — | — | {errors} |")
            continue
        avg_tps = statistics.mean(r.throughput for r in ok_rows)
        avg_lat = statistics.mean(r.elapsed_seconds for r in ok_rows)
        avg_out = statistics.mean(r.completion_tokens for r in ok_rows)
        lines.append(
            f"| `{model}` | {avg_tps:.1f} tok/s | {avg_lat:.1f}s | "
            f"{avg_out:.0f} | {errors} |"
        )
    lines.append("")

    # Per-prompt result table
    lines += [
        "## Per-prompt results",
        "",
        "| Prompt | Model | Latency | Tokens | Throughput |",
        "|---|---|---:|---:|---:|",
    ]
    for prompt in prompts:
        for model in models:
            r = next(
                (x for x in results if x.prompt_id == prompt.id and x.model == model),
                None,
            )
            if r is None:
                continue
            if r.error:
                lines.append(
                    f"| `{prompt.id}` | `{model}` | — | — | error: {r.error[:40]} |"
                )
            else:
                lines.append(
                    f"| `{prompt.id}` | `{model}` | "
                    f"{r.elapsed_seconds:.2f}s | {r.completion_tokens} | "
                    f"{r.throughput:.1f} tok/s |"
                )
    lines.append("")

    # Sample outputs section: one full answer per prompt × model
    lines += ["## Sample outputs", ""]
    for prompt in prompts:
        lines.append(f"### {prompt.id} · _{prompt.description}_")
        lines.append("")
        lines.append(f"> {prompt.text.strip().replace(chr(10), ' ')[:200]}")
        lines.append("")
        for model in models:
            r = next(
                (x for x in results if x.prompt_id == prompt.id and x.model == model),
                None,
            )
            if r is None or r.error:
                continue
            lines.append(f"**`{model}`** — {r.elapsed_seconds:.2f}s, {r.throughput:.1f} tok/s")
            lines.append("")
            answer = r.answer.strip()[:1000]
            lines.append("```")
            lines.append(answer)
            lines.append("```")
            if r.reasoning:
                lines.append(f"<details><summary>hidden reasoning ({len(r.reasoning)} chars)</summary>\n")
                lines.append("```")
                lines.append(r.reasoning[:1500])
                lines.append("```")
                lines.append("</details>")
            lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", help="Comma-separated model names")
    parser.add_argument("--prompts", help="Comma-separated prompt ids (subset)")
    parser.add_argument("--prompts-file", default=str(BENCH_DIR / "prompts.toml"))
    parser.add_argument("--output-json", default=str(BENCH_DIR / "results.json"))
    parser.add_argument("--output-md", default=str(BENCH_DIR / "REPORT.md"))
    args = parser.parse_args()

    all_prompts = load_prompts(Path(args.prompts_file))
    if args.prompts:
        wanted = set(args.prompts.split(","))
        all_prompts = [p for p in all_prompts if p.id in wanted]
    models = args.models.split(",") if args.models else DEFAULT_MODELS

    console.print(
        f"[bold]benchmarking[/bold] {len(all_prompts)} prompts × {len(models)} models "
        f"= {len(all_prompts) * len(models)} runs"
    )

    results: list[RunResult] = []
    started = time.perf_counter()
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("running", total=len(all_prompts) * len(models))
        for prompt in all_prompts:
            for model in models:
                progress.update(task, description=f"{prompt.id} · {model}")
                r = run_single(model, prompt)
                results.append(r)
                status = "ERR" if r.error else f"{r.throughput:.1f} tok/s"
                console.print(
                    f"  [dim]{prompt.id:18s}[/dim] [cyan]{model:18s}[/cyan] "
                    f"[green]{status}[/green]"
                )
                progress.advance(task)
    total_secs = time.perf_counter() - started

    Path(args.output_json).write_text(
        json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False)
    )
    report = render_report(results, all_prompts, models)
    Path(args.output_md).write_text(report)

    console.print()
    console.print(f"[bold green]done[/bold green] in {total_secs:.0f}s")
    console.print(f"  json:   {args.output_json}")
    console.print(f"  report: {args.output_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
