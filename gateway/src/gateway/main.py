"""FastAPI application: routes and app setup."""

from fastapi import FastAPI

app = FastAPI(title="selfhosted-llm-gateway")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness check: the gateway process is up (does not check the backend)."""
    return {"status": "ok"}
