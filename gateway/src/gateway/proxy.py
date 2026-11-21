"""Forward client requests to the llama.cpp backend, streaming the response through."""

import time

import httpx
from fastapi import Request
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

from gateway.errors import error_response
from gateway.metrics import CompletionObserver, observe_stream


async def forward(request: Request, path: str) -> Response:
    """Send the incoming request to the backend and stream the backend's answer back.

    Every response is relayed chunk by chunk, so server-sent events (`"stream": true`)
    reach the client token by token instead of being buffered until generation ends.
    """
    started_at = time.perf_counter()
    client: httpx.AsyncClient = request.app.state.http_client
    body = await request.body()
    headers = {"content-type": request.headers.get("content-type", "application/json")}

    backend_request = client.build_request(
        request.method,
        path,
        content=body or None,
        headers=headers if body else None,
    )
    try:
        # stream=True: return as soon as the response headers arrive, read the body later.
        backend_response = await client.send(backend_request, stream=True)
    except httpx.TimeoutException:
        return error_response(504, "Backend did not respond in time", "backend_timeout")
    except httpx.TransportError:
        return error_response(502, "Backend is unreachable", "backend_unavailable")

    body_stream = backend_response.aiter_bytes()
    if path == "/v1/chat/completions" and backend_response.status_code == 200:
        content_type = backend_response.headers.get("content-type", "")
        observer = CompletionObserver(
            key=request.state.key_id,
            streaming=content_type.startswith("text/event-stream"),
            started_at=started_at,
        )
        body_stream = observe_stream(body_stream, observer)

    return StreamingResponse(
        body_stream,
        status_code=backend_response.status_code,
        media_type=backend_response.headers.get("content-type"),
        # Close the backend connection once the client has received everything.
        background=BackgroundTask(backend_response.aclose),
    )
