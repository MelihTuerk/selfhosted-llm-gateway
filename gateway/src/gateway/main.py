"""FastAPI application: routes and app setup."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Depends, FastAPI, Request, Response

from gateway.auth import require_api_key
from gateway.errors import APIError, handle_api_error
from gateway.proxy import forward
from gateway.settings import get_settings

logger = logging.getLogger("gateway")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create one shared HTTP client for the app's lifetime (reuses backend connections)."""
    settings = get_settings()
    if not settings.api_keys:
        logger.warning("GATEWAY_API_KEYS is empty: every /v1 request will be rejected.")

    timeout = httpx.Timeout(settings.backend_timeout, connect=5.0)
    async with httpx.AsyncClient(base_url=settings.backend_url, timeout=timeout) as client:
        app.state.http_client = client
        yield


app = FastAPI(title="selfhosted-llm-gateway", lifespan=lifespan)
app.add_exception_handler(APIError, handle_api_error)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness check: the gateway process is up (does not check the backend).

    Deliberately open, so Docker's healthcheck works without an API key.
    """
    return {"status": "ok"}


# Every route on this router requires a valid API key.
v1 = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])


@v1.get("/models")
async def list_models(request: Request) -> Response:
    return await forward(request, "/v1/models")


@v1.post("/chat/completions")
async def chat_completions(request: Request) -> Response:
    return await forward(request, "/v1/chat/completions")


app.include_router(v1)
