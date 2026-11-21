import httpx
import pytest
import respx

from gateway.main import app
from gateway.ratelimit import RateLimiter, TokenBucket
from gateway.settings import get_settings

BACKEND = get_settings().backend_url


class FakeClock:
    """Manually advanced clock, so tests control time instead of sleeping."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --- TokenBucket -----------------------------------------------------------------


def test_bucket_allows_a_burst_up_to_capacity():
    bucket = TokenBucket(capacity=3, refill_rate=1)
    assert [bucket.try_acquire(now=0) for _ in range(3)] == [0, 0, 0]
    assert bucket.try_acquire(now=0) > 0


def test_bucket_reports_time_until_next_token():
    bucket = TokenBucket(capacity=1, refill_rate=0.5)  # one token every 2 s
    bucket.try_acquire(now=0)
    assert bucket.try_acquire(now=0) == pytest.approx(2.0)
    assert bucket.try_acquire(now=1.5) == pytest.approx(0.5)


def test_bucket_refills_over_time():
    bucket = TokenBucket(capacity=1, refill_rate=0.5)
    bucket.try_acquire(now=0)
    assert bucket.try_acquire(now=2.0) == 0


def test_bucket_never_exceeds_capacity():
    bucket = TokenBucket(capacity=2, refill_rate=1)
    # A long idle period must not save up more than `capacity` tokens.
    results = [bucket.try_acquire(now=3600) for _ in range(3)]
    assert results[:2] == [0, 0]
    assert results[2] > 0


# --- RateLimiter -----------------------------------------------------------------


def test_limiter_keeps_a_separate_bucket_per_key():
    limiter = RateLimiter(requests_per_minute=60, burst=1, clock=FakeClock())
    assert limiter.check("a") == 0
    assert limiter.check("a") > 0
    # Key "a" being exhausted must not affect key "b".
    assert limiter.check("b") == 0


@pytest.mark.parametrize(("per_minute", "burst"), [(0, 10), (60, 0)])
def test_limiter_is_disabled_by_zero(per_minute, burst):
    limiter = RateLimiter(requests_per_minute=per_minute, burst=burst)
    assert not limiter.enabled
    assert all(limiter.check("a") == 0 for _ in range(100))


# --- Through the HTTP API --------------------------------------------------------


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def limited_client(client, clock):
    """Client whose key may send 2 requests at once, then 1 per 2 seconds."""
    app.state.rate_limiter = RateLimiter(requests_per_minute=30, burst=2, clock=clock)
    with respx.mock:
        respx.get(f"{BACKEND}/v1/models").mock(return_value=httpx.Response(200, json={}))
        yield client


def test_request_over_the_limit_gets_429_with_retry_after(limited_client):
    assert limited_client.get("/v1/models").status_code == 200
    assert limited_client.get("/v1/models").status_code == 200

    response = limited_client.get("/v1/models")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "2"
    assert response.json()["error"]["type"] == "rate_limit_exceeded"


def test_retry_after_rounds_up_to_whole_seconds(limited_client, clock):
    limited_client.get("/v1/models")
    limited_client.get("/v1/models")
    clock.now += 0.5  # 1.5 s left until the next token

    assert limited_client.get("/v1/models").headers["retry-after"] == "2"


def test_client_may_send_again_after_retry_after(limited_client, clock):
    limited_client.get("/v1/models")
    limited_client.get("/v1/models")
    retry_after = int(limited_client.get("/v1/models").headers["retry-after"])

    clock.now += retry_after

    assert limited_client.get("/v1/models").status_code == 200


def test_rejected_request_does_not_reach_the_backend(limited_client):
    for _ in range(3):
        limited_client.get("/v1/models")
    assert respx.calls.call_count == 2


def test_invalid_key_gets_401_not_429(limited_client):
    for _ in range(3):
        limited_client.get("/v1/models")

    # Auth runs before the rate limit, so a wrong key is never told it is "limited".
    response = limited_client.get("/v1/models", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401
    assert "wrong" not in app.state.rate_limiter._buckets
