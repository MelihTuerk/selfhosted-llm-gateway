import httpx
import pytest
import respx

from gateway.settings import get_settings

BACKEND = get_settings().backend_url


def assert_unauthorized(response):
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["type"] == "authentication_error"


def test_missing_key_is_rejected(anon_client):
    assert_unauthorized(anon_client.get("/v1/models"))


@pytest.mark.parametrize(
    "header",
    ["Bearer wrong-key", "Basic dGVzdC1rZXk=", "test-key", "Bearer ", "Bearer tëst"],
)
def test_wrong_or_malformed_key_is_rejected(anon_client, header):
    # Sent as raw UTF-8 bytes, so a non-ASCII key reaches the gateway unchanged.
    headers = {"Authorization": header.encode()}
    assert_unauthorized(anon_client.get("/v1/models", headers=headers))


def test_every_key_is_rejected_when_none_are_configured(client, settings):
    settings.api_keys = []
    assert_unauthorized(client.get("/v1/models"))


def test_auth_also_protects_chat_completions(anon_client):
    assert_unauthorized(anon_client.post("/v1/chat/completions", json={}))


def test_healthz_needs_no_key(anon_client):
    assert anon_client.get("/healthz").status_code == 200


@respx.mock
def test_valid_key_is_accepted_and_not_forwarded(client):
    route = respx.get(f"{BACKEND}/v1/models").mock(return_value=httpx.Response(200, json={}))

    response = client.get("/v1/models")

    assert response.status_code == 200
    # The client's key is for the gateway only and must not leak to the backend.
    assert "authorization" not in route.calls.last.request.headers
