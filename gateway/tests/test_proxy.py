import json

import httpx
import respx

from gateway.settings import get_settings

BACKEND = get_settings().backend_url


@respx.mock
def test_models_are_forwarded(client):
    models = {"object": "list", "data": [{"id": "qwen2.5-0.5b", "object": "model"}]}
    respx.get(f"{BACKEND}/v1/models").mock(return_value=httpx.Response(200, json=models))

    response = client.get("/v1/models")

    assert response.status_code == 200
    assert response.json() == models


@respx.mock
def test_chat_completion_body_is_forwarded_unchanged(client):
    route = respx.post(f"{BACKEND}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "Hi"}}]})
    )
    payload = {"model": "any", "messages": [{"role": "user", "content": "Hello"}]}

    response = client.post("/v1/chat/completions", json=payload)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Hi"
    assert json.loads(route.calls.last.request.content) == payload


@respx.mock
def test_streaming_response_is_relayed(client):
    events = (
        b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    respx.post(f"{BACKEND}/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, content=events, headers={"content-type": "text/event-stream"}
        )
    )

    with client.stream("POST", "/v1/chat/completions", json={"stream": True}) as response:
        body = b"".join(response.iter_bytes())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert body == events


@respx.mock
def test_backend_error_status_is_passed_through(client):
    error = {"error": {"message": "bad request", "type": "invalid_request_error"}}
    respx.post(f"{BACKEND}/v1/chat/completions").mock(return_value=httpx.Response(400, json=error))

    response = client.post("/v1/chat/completions", json={})

    assert response.status_code == 400
    assert response.json() == error


@respx.mock
def test_unreachable_backend_returns_502(client):
    respx.get(f"{BACKEND}/v1/models").mock(side_effect=httpx.ConnectError("refused"))

    response = client.get("/v1/models")

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "backend_unavailable"


@respx.mock
def test_backend_timeout_returns_504(client):
    respx.get(f"{BACKEND}/v1/models").mock(side_effect=httpx.ReadTimeout("slow"))

    response = client.get("/v1/models")

    assert response.status_code == 504
    assert response.json()["error"]["type"] == "backend_timeout"
