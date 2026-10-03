"""Storage selection, counting, and the single 429 implementation (plan §3 A).

`RateLimiter` owns everything slowapi used to: which `limits` storage counts
the hits (Redis, degrading to memory — B4), the fixed-window strategy slowapi
defaulted to, and the one function that turns an exceeded window into the
flat `{message, code}` 429 with `X-RateLimit-*` and `Retry-After` (B5). The
global middleware and the per-route dependency both reach that function
directly (B6), so there is no exception-handler hand-off whose `def` vs
`async def` shape matters any more.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from limits import RateLimitItem, parse
from limits.aio.storage import MemoryStorage, Storage
from limits.aio.strategies import FixedWindowRateLimiter
from limits.storage import storage_from_string
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from collections.abc import Callable

    from limits import WindowStats
    from starlette.requests import Request

__all__ = [
    "RATE_LIMIT_CODE",
    "RATE_LIMIT_MESSAGE",
    "RateLimitDecision",
    "RateLimiter",
    "peer_address",
]

logger = logging.getLogger(__name__)

RATE_LIMIT_MESSAGE = "Rate limit exceeded. Please try again later."
RATE_LIMIT_CODE = "RATE_LIMIT_EXCEEDED"

# How long the limiter stays on the memory fallback before it tries the
# primary storage again. slowapi re-probed on a similar cadence.
_DEFAULT_RECOVERY_SECONDS = 30.0


def peer_address(request: Request) -> str:
    """Return the TCP peer address, the default bucket key.

    Deliberately ignores `X-Forwarded-For`. Trusting that header safely needs
    the trusted-proxy walk `services/api`'s `get_client_identifier` already
    implements (B3), which does not depend on slowapi and is passed in as
    `key_func` there instead of being re-implemented here.

    Args:
        request: The incoming request.

    Returns:
        str: The peer host, or ``"unknown"`` when the transport reports none.
    """
    return request.client.host if request.client else "unknown"


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    """The outcome of one counted hit against one limit."""

    allowed: bool
    item: RateLimitItem
    stats: WindowStats


class RateLimiter:
    """Count hits on `limits` storage and render the shared 429.

    Args:
        default_limit: The limit every HTTP request is counted against by
            `RateLimitMiddleware` (B1), in `limits` notation (``"1000/minute"``).
        storage_uri: A `limits` async storage URI (``"async+redis://…"``), or
            ``None`` for in-process memory. A plain ``redis://`` URI is
            accepted and mapped to its async form.
        key_func: Maps a request to its bucket key (B3 is injected here).
        clock: Wall-clock seconds, used only for `Retry-After`.
        monotonic: Monotonic seconds, used only for the fallback cooldown.
        recovery_seconds: How long to stay on memory after the primary fails.
        storage: Inject a primary storage directly (tests); overrides
            ``storage_uri``.
    """

    def __init__(
        self,
        default_limit: str,
        *,
        storage_uri: str | None = None,
        key_func: Callable[[Request], str] = peer_address,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        recovery_seconds: float = _DEFAULT_RECOVERY_SECONDS,
        storage: Storage | None = None,
    ) -> None:
        self.default_limit: RateLimitItem = parse(default_limit)
        self.key_func = key_func
        self._clock = clock
        self._monotonic = monotonic
        self._recovery_seconds = recovery_seconds
        self._fallback = MemoryStorage()
        self._primary: Storage | None = storage or _primary_from_uri(storage_uri)
        self._degraded_until: float | None = None

    @property
    def degraded(self) -> bool:
        """Whether hits are currently counted on the memory fallback."""
        return self._degraded_until is not None

    async def hit(self, item: RateLimitItem, key: str) -> RateLimitDecision:
        """Count one hit against ``item`` for ``key`` and read the window back.

        A primary-storage failure at any point — the first request after
        start-up included, so an unreachable Redis at boot needs no separate
        probe — moves counting to memory with one warning (B4). After
        ``recovery_seconds`` the next hit tries the primary again.

        Args:
            item: The limit to count against.
            key: The bucket key, usually ``key_func(request)``.

        Returns:
            RateLimitDecision: Whether the hit fit, and the window after it.
        """
        primary = self._primary
        if primary is not None and self._primary_available():
            try:
                return await _count(primary, item, key)
            except Exception:  # noqa: BLE001 — any storage failure degrades, never 500s
                self._degrade()
        return await _count(self._fallback, item, key)

    def headers(self, decision: RateLimitDecision, *, retry_after: bool) -> dict[str, str]:
        """Render the `X-RateLimit-*` headers for ``decision``.

        Values follow slowapi's on-the-wire shape so existing clients keep
        parsing them: `X-RateLimit-Reset` is an epoch-seconds integer and
        `Retry-After` is delay-seconds, never an HTTP-date.

        Args:
            decision: The counted hit.
            retry_after: Add `Retry-After`. Only a 429 carries it; slowapi
                also sent it on 2xx, where RFC 9110 gives it no meaning.

        Returns:
            dict[str, str]: Header name to value.
        """
        reset_at = math.ceil(decision.stats.reset_time)
        headers = {
            "X-RateLimit-Limit": str(decision.item.amount),
            "X-RateLimit-Remaining": str(decision.stats.remaining),
            "X-RateLimit-Reset": str(reset_at),
        }
        if retry_after:
            headers["Retry-After"] = str(max(1, math.ceil(reset_at - self._clock())))
        return headers

    def exceeded_response(self, decision: RateLimitDecision) -> JSONResponse:
        """Build the one 429 both enforcement paths return (B5, B6).

        Args:
            decision: The hit that did not fit.

        Returns:
            JSONResponse: The flat `{message, code}` body with rate-limit headers.
        """
        return JSONResponse(
            status_code=429,
            content={"message": RATE_LIMIT_MESSAGE, "code": RATE_LIMIT_CODE},
            headers=self.headers(decision, retry_after=True),
        )

    def _primary_available(self) -> bool:
        if self._degraded_until is None:
            return True
        if self._monotonic() < self._degraded_until:
            return False
        logger.info("Retrying primary rate-limit storage")
        self._degraded_until = None
        return True

    def _degrade(self) -> None:
        logger.warning(
            "Rate limit storage unreachable - falling back to in-memory storage for %.0fs",
            self._recovery_seconds,
        )
        self._degraded_until = self._monotonic() + self._recovery_seconds


async def _count(storage: Storage, item: RateLimitItem, key: str) -> RateLimitDecision:
    strategy = FixedWindowRateLimiter(storage)
    allowed = await strategy.hit(item, key)
    stats = await strategy.get_window_stats(item, key)
    return RateLimitDecision(allowed=allowed, item=item, stats=stats)


def _primary_from_uri(storage_uri: str | None) -> Storage | None:
    if storage_uri is None:
        return None
    if storage_uri.startswith(("redis://", "rediss://")):
        storage_uri = f"async+{storage_uri}"
    # `redispy` (redis.asyncio) rather than limits' default `coredis`, so the
    # lane needs only the `redis` package the hub already depends on.
    # `wrap_exceptions` turns driver errors into `limits.errors.StorageError`.
    options: dict[str, float | str | bool] = {"implementation": "redispy", "wrap_exceptions": True}
    if not storage_uri.startswith("async+redis"):
        options = {}
    storage = storage_from_string(storage_uri, **options)
    if not isinstance(storage, Storage):
        msg = f"rate-limit storage URI must use an async+ scheme, got {storage_uri!r}"
        raise ValueError(msg)
    return storage
