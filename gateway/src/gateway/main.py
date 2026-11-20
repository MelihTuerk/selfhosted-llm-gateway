"""FastAPI application: routes and app setup."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response

from gateway.proxy import forward
from gateway.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create one shared HTTP client for the app's lifetime (reuses backend connections)."""
    settings = get_settings()
    timeout = httpx.Timeout(settings.backend_timeout, connect=5.0)
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=timeout) as client:
        app.state.http_client = client
        yield


app = FastAPI(title="selfhosted-llm-gateway", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness check: the gateway process is up (does not check the backend)."""
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models(request: Request) -> Response:
    return await forward(request, "/v1/models")


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    return await forward(request, "/v1/chat/completions")
