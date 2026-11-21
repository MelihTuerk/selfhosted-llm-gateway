"""Per-API-key rate limiting with an in-memory token bucket."""

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request

from gateway.auth import require_api_key
from gateway.errors import APIError


@dataclass
class TokenBucket:
    """Holds up to `capacity` tokens and refills at `refill_rate` tokens per second.

    Every request takes one token. A full bucket allows a burst of `capacity` requests;
    after that, requests are allowed at the refill rate.
    """

    capacity: float
    refill_rate: float
    tokens: float = field(init=False)
    updated_at: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.tokens = self.capacity

    def try_acquire(self, now: float) -> float:
        """Take one token if possible.

        Returns 0 when the request is allowed, otherwise the seconds until a token is free.
        """
        # Refill lazily: instead of a background timer, add the tokens that accumulated
        # since the last call. The bucket never holds more than `capacity`.
        if self.updated_at is not None:
            elapsed = now - self.updated_at
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.updated_at = now

        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        return (1 - self.tokens) / self.refill_rate


class RateLimiter:
    """One token bucket per API key.

    Only keys that passed authentication get here, so the number of buckets is bounded
    by the configured keys. State lives in this process: limits reset on restart and are
    not shared between several gateway instances.
    """

    def __init__(
        self,
        requests_per_minute: float,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.enabled = requests_per_minute > 0 and burst > 0
        self._refill_rate = requests_per_minute / 60
        self._burst = burst
        # monotonic, not time.time(): it never jumps when the system clock is adjusted.
        self._clock = clock
        self._buckets: dict[str, TokenBucket] = {}

    def check(self, key: str) -> float:
        """Return 0 if `key` may send a request now, otherwise the seconds to wait."""
        if not self.enabled:
            return 0.0
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = self._buckets[key] = TokenBucket(self._burst, self._refill_rate)
        return bucket.try_acquire(self._clock())


async def enforce_rate_limit(
    request: Request,
    api_key: Annotated[str, Depends(require_api_key)],
) -> None:
    """Reject the request with 429 when the caller's key has used up its budget.

    Declared `async` on purpose: it then runs on the event loop, one request at a time,
    so the buckets need no lock. (Sync dependencies would run in a thread pool.)
    """
    limiter: RateLimiter = request.app.state.rate_limiter
    wait = limiter.check(api_key)
    if wait > 0:
        # Retry-After takes whole seconds; round up so a client that waits exactly
        # this long is guaranteed to get a token.
        retry_after = max(1, math.ceil(wait))
        raise APIError(
            429,
            f"Rate limit exceeded. Retry in {retry_after} s.",
            "rate_limit_exceeded",
            {"Retry-After": str(retry_after)},
        )
