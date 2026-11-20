"""Errors sent to clients in the same JSON shape the OpenAI API uses."""

from fastapi import Request
from fastapi.responses import JSONResponse


class APIError(Exception):
    """Raise anywhere in a request to answer with an OpenAI-style error body."""

    def __init__(
        self,
        status_code: int,
        message: str,
        error_type: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        self.headers = headers


def error_response(
    status_code: int,
    message: str,
    error_type: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type}},
        headers=headers,
    )


async def handle_api_error(request: Request, exc: APIError) -> JSONResponse:
    return error_response(exc.status_code, exc.message, exc.error_type, exc.headers)
