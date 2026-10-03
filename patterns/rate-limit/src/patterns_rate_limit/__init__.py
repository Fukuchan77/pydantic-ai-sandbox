"""Rate limiting on `limits` directly — the slowapi replacement verification lane.

See ``docs/slowapi-replacement-plan.md`` at the repository root for why this
lane exists and what it must prove before the hub takes it.
"""

from patterns_rate_limit.limiter import (
    RATE_LIMIT_CODE,
    RATE_LIMIT_MESSAGE,
    RateLimitDecision,
    RateLimiter,
    peer_address,
)
from patterns_rate_limit.middleware import (
    RateLimitExceededError,
    RateLimitMiddleware,
    add_rate_limiting,
    get_rate_limiter,
    rate_limit,
)

__all__ = [
    "RATE_LIMIT_CODE",
    "RATE_LIMIT_MESSAGE",
    "RateLimitDecision",
    "RateLimitExceededError",
    "RateLimitMiddleware",
    "RateLimiter",
    "add_rate_limiting",
    "get_rate_limiter",
    "peer_address",
    "rate_limit",
]
