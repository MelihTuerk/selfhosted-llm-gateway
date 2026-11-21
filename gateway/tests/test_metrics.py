import httpx
import pytest
import respx
from conftest import TEST_KEY
from prometheus_client import REGISTRY

from gateway.metrics import CompletionObserver, key_id
from gateway.settings import get_settings

BACKEND = get_settings().backend_url
CHAT = f"{BACKEND}/v1/chat/completions"
TEST_KEY_ID = key_id(TEST_KEY)


def sample(name, **labels):
    """Current value of one metric sample (0 if it does not exist yet)."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def delta():
    """Returns how much a sample changed since the test started."""
    seen = {}

    def measure(name, **labels):
        key = (name, tuple(sorted(labels.items())))
        if key not in seen:
            raise AssertionError(f"call delta.start({name!r}, ...) first")
        return sample(name, **labels) - seen[key]

    def start(name, **labels):
        seen[(name, tuple(sorted(labels.items())))] = sample(name, **labels)

    measure.start = start
    return measure


def sse(*events: str) -> bytes:
    return b"".join(f"data: {event}\n\n".encode() for event in events)


STREAM = sse(
    '{"choices":[{"delta":{"role":"assistant","content":null}}]}',
    '{"choices":[{"delta":{"content":"Hel"}}]}',
    '{"choices":[{"delta":{"content":"lo"}}]}',
    '{"choices":[{"delta":{"content":"!"}}]}',
    '{"choices":[{"finish_reason":"stop","delta":{}}],"timings":{"predicted_n":3}}',
    "[DONE]",
)


def stream_response(body: bytes = STREAM) -> httpx.Response:
    return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})


# --- /metrics endpoint -----------------------------------------------------------


def test_metrics_endpoint_is_open_and_in_prometheus_format(anon_client):
    response = anon_client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "gateway_requests_total" in response.text


@respx.mock
def test_raw_api_key_never_appears_in_metrics(client):
    respx.post(CHAT).mock(return_value=stream_response())
    client.post("/v1/chat/completions", json={"stream": True})

    text = client.get("/metrics").text

    assert TEST_KEY not in text
    assert f'key="{TEST_KEY_ID}"' in text


# --- Request counter and duration ------------------------------------------------


@respx.mock
def test_successful_request_is_counted_with_key_id(client, delta):
    labels = {"endpoint": "/v1/models", "status": "200", "key": TEST_KEY_ID}
    delta.start("gateway_requests_total", **labels)
    delta.start("gateway_request_duration_seconds_count", endpoint="/v1/models")
    respx.get(f"{BACKEND}/v1/models").mock(return_value=httpx.Response(200, json={}))

    client.get("/v1/models")

    assert delta("gateway_requests_total", **labels) == 1
    assert delta("gateway_request_duration_seconds_count", endpoint="/v1/models") == 1


def test_rejected_request_is_counted_without_key(anon_client, delta):
    labels = {"endpoint": "/v1/models", "status": "401", "key": "none"}
    delta.start("gateway_requests_total", **labels)

    anon_client.get("/v1/models")

    assert delta("gateway_requests_total", **labels) == 1


@respx.mock
def test_backend_error_status_is_counted(client, delta):
    labels = {"endpoint": "/v1/chat/completions", "status": "502", "key": TEST_KEY_ID}
    delta.start("gateway_requests_total", **labels)
    respx.post(CHAT).mock(side_effect=httpx.ConnectError("down"))

    client.post("/v1/chat/completions", json={})

    assert delta("gateway_requests_total", **labels) == 1


def test_unknown_paths_share_one_label(client, delta):
    labels = {"endpoint": "other", "status": "404", "key": "none"}
    delta.start("gateway_requests_total", **labels)

    client.get("/v1/does-not-exist-1")
    client.get("/v1/does-not-exist-2")

    assert delta("gateway_requests_total", **labels) == 2


def test_non_v1_paths_are_not_counted(client, delta):
    labels = {"endpoint": "other", "status": "200", "key": "none"}
    delta.start("gateway_requests_total", **labels)

    client.get("/healthz")
    client.get("/metrics")

    assert delta("gateway_requests_total", **labels) == 0


# --- Token metrics through the proxy ---------------------------------------------


@respx.mock
def test_streaming_completion_records_ttft_tokens_and_speed(client, delta):
    delta.start("gateway_time_to_first_token_seconds_count")
    delta.start("gateway_tokens_per_second_count")
    delta.start("gateway_tokens_generated_total", key=TEST_KEY_ID)
    respx.post(CHAT).mock(return_value=stream_response())

    response = client.post("/v1/chat/completions", json={"stream": True})

    assert response.content == STREAM  # metrics must not change the bytes
    assert delta("gateway_time_to_first_token_seconds_count") == 1
    assert delta("gateway_tokens_per_second_count") == 1
    assert delta("gateway_tokens_generated_total", key=TEST_KEY_ID) == 3


@respx.mock
def test_non_streaming_completion_counts_usage_tokens(client, delta):
    delta.start("gateway_tokens_generated_total", key=TEST_KEY_ID)
    delta.start("gateway_time_to_first_token_seconds_count")
    body = {"choices": [{"message": {"content": "Hi"}}], "usage": {"completion_tokens": 7}}
    respx.post(CHAT).mock(return_value=httpx.Response(200, json=body))

    client.post("/v1/chat/completions", json={})

    assert delta("gateway_tokens_generated_total", key=TEST_KEY_ID) == 7
    # Without streaming the client sees no "first token" before the end: no TTFT sample.
    assert delta("gateway_time_to_first_token_seconds_count") == 0


@respx.mock
def test_backend_error_records_no_token_metrics(client, delta):
    delta.start("gateway_tokens_generated_total", key=TEST_KEY_ID)
    respx.post(CHAT).mock(return_value=httpx.Response(400, json={"error": {}}))

    client.post("/v1/chat/completions", json={})

    assert delta("gateway_tokens_generated_total", key=TEST_KEY_ID) == 0


# --- CompletionObserver on its own -----------------------------------------------


def test_observer_handles_events_split_across_chunks(delta):
    delta.start("gateway_tokens_generated_total", key="split")
    observer = CompletionObserver(key="split", streaming=True, started_at=0)

    # Cut the stream at awkward places, including inside the JSON of an event.
    for i in range(0, len(STREAM), 7):
        observer.feed(STREAM[i : i + 7])
    observer.finish()

    assert delta("gateway_tokens_generated_total", key="split") == 3


def test_observer_prefers_usage_over_timings(delta):
    delta.start("gateway_tokens_generated_total", key="usage")
    observer = CompletionObserver(key="usage", streaming=True, started_at=0)

    observer.feed(sse('{"choices":[],"usage":{"completion_tokens":5},"timings":{"predicted_n":4}}'))
    observer.finish()

    assert delta("gateway_tokens_generated_total", key="usage") == 5


def test_observer_falls_back_to_counting_content_events(delta):
    delta.start("gateway_tokens_generated_total", key="count")
    observer = CompletionObserver(key="count", streaming=True, started_at=0)

    token = '{"choices":[{"delta":{"content":"x"}}]}'
    observer.feed(sse(token, token))
    observer.finish()

    assert delta("gateway_tokens_generated_total", key="count") == 2


def test_observer_ignores_garbage(delta):
    delta.start("gateway_tokens_generated_total", key="junk")
    observer = CompletionObserver(key="junk", streaming=True, started_at=0)

    observer.feed(b": keep-alive comment\n\ndata: not json\n\ndata: [DONE]\n\n")
    observer.finish()

    assert delta("gateway_tokens_generated_total", key="junk") == 0
