"""Prometheus metrics: request counts and latency for every /v1 call, plus LLM-specific
numbers (time to first token, tokens per second, generated tokens) for chat completions."""

import contextlib
import hashlib
import json
import time
from collections.abc import AsyncIterator

from prometheus_client import Counter, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Fixed set of endpoint labels. Unknown paths share one label, so a scanner hitting
# random URLs cannot create unlimited time series (high label cardinality).
KNOWN_ENDPOINTS = {"/v1/models", "/v1/chat/completions"}

REQUESTS = Counter(
    "gateway_requests",
    "Requests to /v1 endpoints, by endpoint, HTTP status and API key id.",
    ["endpoint", "status", "key"],
)
REQUEST_DURATION = Histogram(
    "gateway_request_duration_seconds",
    "Time from request start until the last byte of the response was sent.",
    ["endpoint"],
    # LLM requests take seconds to minutes, far longer than the default buckets assume.
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
TIME_TO_FIRST_TOKEN = Histogram(
    "gateway_time_to_first_token_seconds",
    "Streaming chat completions: time until the first generated text reached the gateway.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
)
TOKENS_PER_SECOND = Histogram(
    "gateway_tokens_per_second",
    "Streaming chat completions: generation speed after the first token.",
    buckets=(1, 2, 5, 10, 20, 30, 50, 75, 100, 150, 200),
)
TOKENS_GENERATED = Counter(
    "gateway_tokens_generated",
    "Completion tokens generated, by API key id.",
    ["key"],
)


def key_id(api_key: str) -> str:
    """Short, stable id for an API key, safe to show in metrics and dashboards.

    The raw key must never become a label: /metrics is readable without auth.
    """
    return hashlib.sha256(api_key.encode()).hexdigest()[:8]


class MetricsMiddleware:
    """Pure ASGI middleware that counts and times every /v1 request.

    Sits outside FastAPI, so it also sees requests rejected by auth (401) or the rate
    limit (429). A pure ASGI middleware (not BaseHTTPMiddleware) passes streamed
    responses through untouched.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/v1/"):
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = 500  # stays 500 if the app crashes before sending a response

        async def send_and_capture_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            # Returns only after the whole (possibly streamed) body was sent,
            # or the client disconnected.
            await self.app(scope, receive, send_and_capture_status)
        finally:
            path = scope["path"]
            endpoint = path if path in KNOWN_ENDPOINTS else "other"
            # Set by require_api_key; missing when auth failed.
            key = scope.get("state", {}).get("key_id", "none")
            REQUESTS.labels(endpoint, str(status), key).inc()
            REQUEST_DURATION.labels(endpoint).observe(time.perf_counter() - start)


class CompletionObserver:
    """Reads a chat completion response as it passes through and records token metrics.

    Works for both streamed (server-sent events) and plain JSON responses. Never changes
    or delays the bytes; it only looks at them.
    """

    # A non-streamed completion is one JSON document; keep at most this much of it.
    MAX_JSON_BYTES = 1_000_000

    def __init__(self, key: str, streaming: bool, started_at: float) -> None:
        self.key = key
        self.streaming = streaming
        self.started_at = started_at
        self._buffer = b""
        self._first_token_at: float | None = None
        self._last_token_at: float | None = None
        self._content_chunks = 0
        # Token count reported by the backend, if any (preferred over counting chunks).
        self._reported_tokens: int | None = None

    def feed(self, chunk: bytes) -> None:
        if not self.streaming:
            if len(self._buffer) < self.MAX_JSON_BYTES:
                self._buffer += chunk
            return

        # A network chunk can end in the middle of an event; keep the incomplete
        # last line in the buffer until the rest arrives.
        self._buffer += chunk
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            self._handle_sse_line(line.strip())

    def _handle_sse_line(self, line: bytes) -> None:
        if not line.startswith(b"data:"):
            return
        payload = line[len(b"data:") :].strip()
        if payload == b"[DONE]":
            return
        try:
            event = json.loads(payload)
        except ValueError:
            return

        if any((choice.get("delta") or {}).get("content") for choice in event.get("choices", [])):
            now = time.perf_counter()
            if self._first_token_at is None:
                self._first_token_at = now
                TIME_TO_FIRST_TOKEN.observe(now - self.started_at)
            self._last_token_at = now
            self._content_chunks += 1

        self._read_token_count(event)

    def _read_token_count(self, body: dict) -> None:
        # OpenAI standard field; llama.cpp sends it when the client asks for it with
        # stream_options.include_usage, and always for non-streamed responses.
        usage = body.get("usage") or {}
        if isinstance(usage.get("completion_tokens"), int):
            self._reported_tokens = usage["completion_tokens"]
            return
        # llama.cpp-specific: its last stream event always carries timings.
        timings = body.get("timings") or {}
        if isinstance(timings.get("predicted_n"), int):
            self._reported_tokens = timings["predicted_n"]

    def finish(self) -> None:
        """Record the totals. Called once the response ended (or the client left)."""
        if not self.streaming:
            with contextlib.suppress(ValueError):
                self._read_token_count(json.loads(self._buffer))

        # Fallback: llama.cpp sends one token per stream event.
        tokens = self._reported_tokens
        if tokens is None:
            tokens = self._content_chunks
        if tokens:
            TOKENS_GENERATED.labels(self.key).inc(tokens)

        # Generation speed: the n-1 tokens after the first one, over the time they took.
        # Leaving out the first token separates it from prompt processing (that is TTFT).
        if self._first_token_at is not None and self._last_token_at is not None:
            duration = self._last_token_at - self._first_token_at
            if tokens > 1 and duration > 0:
                TOKENS_PER_SECOND.observe((tokens - 1) / duration)


async def observe_stream(
    chunks: AsyncIterator[bytes], observer: CompletionObserver
) -> AsyncIterator[bytes]:
    """Yield every chunk unchanged while feeding it to the observer."""
    try:
        async for chunk in chunks:
            observer.feed(chunk)
            yield chunk
    finally:
        # Runs also when the client disconnects mid-stream: partial results still count.
        observer.finish()
