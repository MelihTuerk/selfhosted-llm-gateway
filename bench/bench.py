# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27", "matplotlib>=3.9"]
# ///
"""Benchmark the LLM stack through the gateway.

Sends streaming chat completions at several concurrency levels and measures, per request:
time to first token (TTFT), generation speed (tokens/s after the first token) and total
latency; per level also the aggregate throughput of all parallel requests together.

Usage (stack must be running):
    GATEWAY_API_KEY=<key> uv run bench/bench.py run --label gpu-q4 --hardware "GTX 1060 6GB"
    uv run bench/bench.py plot          # all CSVs in bench/results -> PNG + Markdown table
Optional: GATEWAY_URL (default http://127.0.0.1:8000/v1)

Fairness:
- One warm-up request first (CUDA kernels compile on first use, caches fill).
- Every prompt starts with a unique ID, so llama.cpp cannot reuse a cached prompt prefix.
- ignore_eos (llama.cpp extension) makes every request generate exactly --max-tokens.
"""

import argparse
import asyncio
import csv
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path

import httpx

RESULTS_DIR = Path(__file__).parent / "results"
FIELDS = [
    "label", "hardware", "model", "concurrency", "request",
    "prompt_tokens", "completion_tokens", "ttft_s", "gen_tps", "latency_s", "level_wall_s",
]  # fmt: skip
# Filler text to reach a fixed prompt length; ~1.3 tokens per word for English text.
FILLER = (
    "The quick brown fox jumps over the lazy dog while the river keeps flowing past the old "
    "mill, and the miller counts sacks of grain for the coming winter months. "
)


def make_prompt(words: int) -> str:
    filler = (FILLER * (words // len(FILLER.split()) + 1)).split()[:words]
    # Unique prefix: defeats llama.cpp's prompt cache, so every request does full prefill.
    return f"Request {uuid.uuid4()}. Read the text and then continue it.\n\n" + " ".join(filler)


async def one_request(client: httpx.AsyncClient, args: argparse.Namespace) -> dict:
    body = {
        "messages": [{"role": "user", "content": make_prompt(args.prompt_words)}],
        "max_tokens": args.max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "ignore_eos": True,
    }
    started = time.perf_counter()
    first_token_at = None
    chunks = 0
    usage = {}
    async with client.stream("POST", "/chat/completions", json=body) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[6:])
            usage = event.get("usage") or usage
            for choice in event.get("choices", []):
                if choice.get("delta", {}).get("content"):
                    chunks += 1
                    first_token_at = first_token_at or time.perf_counter()
    finished = time.perf_counter()

    if first_token_at is None:
        raise RuntimeError("stream ended without any content")
    completion_tokens = usage.get("completion_tokens", chunks)
    gen_time = finished - first_token_at
    return {
        "prompt_tokens": usage.get("prompt_tokens", ""),
        "completion_tokens": completion_tokens,
        "ttft_s": round(first_token_at - started, 4),
        # Tokens after the first one, divided by the time they took.
        "gen_tps": round((completion_tokens - 1) / gen_time, 2) if gen_time > 0 else "",
        "latency_s": round(finished - started, 4),
    }


async def run_level(client: httpx.AsyncClient, args: argparse.Namespace, concurrency: int):
    """Run args.requests requests with at most `concurrency` in flight at once."""
    limit = asyncio.Semaphore(concurrency)

    async def limited() -> dict:
        async with limit:
            return await one_request(client, args)

    started = time.perf_counter()
    results = await asyncio.gather(*(limited() for _ in range(args.requests)))
    return results, time.perf_counter() - started


async def run(args: argparse.Namespace) -> int:
    key = os.environ.get("GATEWAY_API_KEY")
    if not key:
        print("Set GATEWAY_API_KEY to one of the keys in GATEWAY_API_KEYS.", file=sys.stderr)
        return 2
    base_url = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8000/v1")
    headers = {"Authorization": f"Bearer {key}"}
    timeout = httpx.Timeout(600, connect=10)

    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=timeout) as client:
        model = (await client.get("/models")).json()["data"][0]["id"]
        print(f"Model {model} at {base_url}, label {args.label!r}")
        await one_request(client, args)  # warm-up, not recorded

        rows = []
        for concurrency in args.concurrency:
            results, wall = await run_level(client, args, concurrency)
            for i, result in enumerate(results, 1):
                rows.append({"label": args.label, "hardware": args.hardware, "model": model,
                             "concurrency": concurrency, "request": i,
                             "level_wall_s": round(wall, 3), **result})  # fmt: skip
            tokens = sum(r["completion_tokens"] for r in results)
            print(
                f"  concurrency {concurrency}: "
                f"TTFT median {statistics.median(r['ttft_s'] for r in results):.3f} s, "
                f"per request {statistics.median(r['gen_tps'] for r in results):.1f} tok/s, "
                f"aggregate {tokens / wall:.1f} tok/s"
            )

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"{args.label}.csv"
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {out}")
    return 0


def summarize(rows: list[dict]) -> list[dict]:
    """One line per (label, concurrency): medians, p95 TTFT and aggregate throughput."""
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        groups.setdefault((row["label"], int(row["concurrency"])), []).append(row)
    summary = []
    for (label, concurrency), group in groups.items():
        ttfts = sorted(float(r["ttft_s"]) for r in group)
        tokens = sum(int(r["completion_tokens"]) for r in group)
        summary.append({
            "label": label, "hardware": group[0]["hardware"], "model": group[0]["model"],
            "concurrency": concurrency, "requests": len(group),
            "ttft_median": statistics.median(ttfts),
            "ttft_p95": ttfts[max(0, round(0.95 * len(ttfts)) - 1)],
            "gen_tps_median": statistics.median(float(r["gen_tps"]) for r in group),
            "latency_median": statistics.median(float(r["latency_s"]) for r in group),
            "aggregate_tps": tokens / float(group[0]["level_wall_s"]),
        })  # fmt: skip
    return summary


def plot(_: argparse.Namespace) -> int:
    import matplotlib

    matplotlib.use("Agg")  # no display needed
    import matplotlib.pyplot as plt

    rows = []
    for path in sorted(RESULTS_DIR.glob("*.csv")):
        with path.open() as f:
            rows += list(csv.DictReader(f))
    if not rows:
        print(f"No CSV files in {RESULTS_DIR}", file=sys.stderr)
        return 1
    summary = summarize(rows)

    panels = [
        ("ttft_median", "Time to first token (median, s)"),
        ("gen_tps_median", "Generation speed per request (median, tok/s)"),
        ("aggregate_tps", "Aggregate throughput (tok/s)"),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    for ax, (field, title) in zip(axes, panels, strict=True):
        for label in dict.fromkeys(s["label"] for s in summary):
            points = sorted((s["concurrency"], s[field]) for s in summary if s["label"] == label)
            ax.plot(*zip(*points, strict=True), marker="o", label=label)
        ax.set_title(title)
        ax.set_xlabel("concurrent requests")
        ax.set_xticks(sorted({s["concurrency"] for s in summary}))
        ax.set_ylim(bottom=0)
        ax.grid(alpha=0.3)
    axes[0].legend()
    fig.tight_layout()
    png = RESULTS_DIR / "benchmark.png"
    fig.savefig(png, dpi=120)

    lines = [
        "| Run | Hardware | Model | Parallel | TTFT median | TTFT p95 "
        "| Tokens/s per request | Tokens/s total |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for s in summary:
        lines.append(
            f"| {s['label']} | {s['hardware']} | {s['model']} | {s['concurrency']} "
            f"| {s['ttft_median']:.2f} s | {s['ttft_p95']:.2f} s "
            f"| {s['gen_tps_median']:.1f} | {s['aggregate_tps']:.1f} |"
        )
    table = RESULTS_DIR / "summary.md"
    table.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"Wrote {png} and {table}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="benchmark the running stack, write bench/results/LABEL.csv")
    run_p.add_argument("--label", required=True, help="run name, e.g. gpu-q4 (CSV file name)")
    run_p.add_argument("--hardware", required=True, help='e.g. "GTX 1060 6GB" or "i5-8400 CPU"')
    run_p.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4])
    run_p.add_argument("--requests", type=int, default=8, help="requests per concurrency level")
    run_p.add_argument("--prompt-words", type=int, default=200, help="prompt length in words")
    run_p.add_argument("--max-tokens", type=int, default=128, help="tokens to generate")
    sub.add_parser("plot", help="combine all CSVs into benchmark.png and summary.md")

    args = parser.parse_args()
    return asyncio.run(run(args)) if args.command == "run" else plot(args)


if __name__ == "__main__":
    sys.exit(main())
