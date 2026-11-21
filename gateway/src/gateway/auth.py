"""API key authentication via the `Authorization: Bearer <key>` header."""

import secrets
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gateway.errors import APIError
from gateway.metrics import key_id
from gateway.settings import Settings, get_settings

# auto_error=False: return None instead of FastAPI's default error,
# so we can answer in the OpenAI error format ourselves.
bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(message: str) -> APIError:
    # RFC 6750: a 401 tells the client which auth scheme is expected.
    return APIError(401, message, "authentication_error", {"WWW-Authenticate": "Bearer"})


def require_api_key(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> str:
    """Reject the request unless it carries one of the configured API keys.

    With no keys configured every request is rejected (fail closed).
    Returns the key so later steps (rate limit, metrics) can tell clients apart.
    """
    if credentials is None:
        raise _unauthorized("Missing API key. Send it as 'Authorization: Bearer <key>'.")

    token = credentials.credentials.encode()
    # compare_digest needs the same time no matter where two keys differ,
    # so response times do not reveal how much of a guessed key was right.
    if not any(secrets.compare_digest(token, key.encode()) for key in settings.api_keys):
        raise _unauthorized("Invalid API key.")

    # Metrics label requests with this short hash instead of the secret key.
    request.state.key_id = key_id(credentials.credentials)
    return credentials.credentials
