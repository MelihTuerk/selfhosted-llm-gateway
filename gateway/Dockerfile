# syntax=docker/dockerfile:1

# ---- Build stage: install dependencies and the gateway into a virtualenv ----
FROM python:3.14-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv

# Compile .py files at build time (faster start); copy instead of hardlinking from the
# uv cache; use the image's Python instead of downloading one.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first: this layer stays cached as long as the lock file does not change.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Then the gateway itself, installed as a regular (non-editable) package.
COPY src ./src
RUN uv sync --locked --no-dev --no-editable


# ---- Runtime stage: only Python and the virtualenv, no uv, no sources ----
FROM python:3.14-slim

# Run as an unprivileged user instead of root.
RUN useradd --system --uid 10001 --no-create-home gateway

COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

USER gateway
EXPOSE 8000

# The slim image has no curl, so the check uses Python's standard library.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
