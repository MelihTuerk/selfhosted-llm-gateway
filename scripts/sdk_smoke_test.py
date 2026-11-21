# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.50"]
# ///
"""Smoke test: talk to the running gateway with the official OpenAI Python SDK.

Proves the gateway is a drop-in OpenAI endpoint: the unmodified client lists models,
gets a normal completion, streams token by token, and receives a proper error for a
wrong key.

Usage (stack must be running):
    GATEWAY_API_KEY=<key> uv run scripts/sdk_smoke_test.py
Optional: GATEWAY_URL (default http://127.0.0.1:8000/v1)
"""

import os
import sys
import time

import openai

BASE_URL = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8000/v1")
API_KEY = os.environ.get("GATEWAY_API_KEY")
PROMPT = [{"role": "user", "content": "Count from 1 to 5, separated by spaces."}]


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{f' - {detail}' if detail else ''}")
    return ok


def main() -> int:
    if not API_KEY:
        print("Set GATEWAY_API_KEY to one of the keys in GATEWAY_API_KEYS.", file=sys.stderr)
        return 2

    client = openai.OpenAI(base_url=BASE_URL, api_key=API_KEY, max_retries=0)
    results = []

    models = client.models.list()
    model = models.data[0].id if models.data else ""
    results.append(check("list models", bool(model), model))

    completion = client.chat.completions.create(model=model, messages=PROMPT, max_tokens=30)
    text = completion.choices[0].message.content or ""
    tokens = completion.usage.completion_tokens if completion.usage else 0
    results.append(check("chat completion", bool(text), f"{tokens} tokens: {text!r}"))

    # Streaming: content must arrive in several pieces, not as one block at the end.
    started = time.perf_counter()
    first_token_at = None
    pieces = []
    stream = client.chat.completions.create(
        model=model, messages=PROMPT, max_tokens=30, stream=True
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            first_token_at = first_token_at or time.perf_counter()
            pieces.append(delta)
    ttft = (first_token_at - started) if first_token_at else float("nan")
    results.append(
        check(
            "streaming",
            len(pieces) > 1,
            f"{len(pieces)} chunks, first after {ttft:.2f} s: {''.join(pieces)!r}",
        )
    )

    bad_client = openai.OpenAI(base_url=BASE_URL, api_key="wrong-key", max_retries=0)
    try:
        bad_client.models.list()
        results.append(check("wrong key rejected", False, "request succeeded"))
    except openai.AuthenticationError as error:
        results.append(check("wrong key rejected", True, f"401: {error.message}"))

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
