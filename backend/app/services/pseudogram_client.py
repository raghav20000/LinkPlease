"""
Thin async client around the PseudoGram API's DM endpoints.

Handles exactly two calls: send a DM, and poll a DM's status. Retry
policy and rate limiting are applied here (see rate_limiter.py) so
every caller gets the same throttling for free.
"""
import httpx

from app.config import get_settings
from app.services.rate_limiter import RollingWindowRateLimiter

_settings = get_settings()

# Shared across the whole process -- this IS the 10-req/60s budget.
dm_send_rate_limiter = RollingWindowRateLimiter(
    max_calls=_settings.pseudogram_rate_limit_per_minute, window_seconds=60.0
)


class PseudoGramClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        settings = get_settings()
        self.base_url = base_url or settings.pseudogram_base_url
        self.api_key = api_key or settings.pseudogram_api_key

    def _headers(self, idempotency_key: str | None = None) -> dict:
        headers = {"X-API-Key": self.api_key}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def send_dm(
        self, recipient_user_id: str, message: str, comment_id: str, idempotency_key: str
    ) -> httpx.Response:
        # Respect the rate limit BEFORE spending a request, not after
        # getting a 429 back.
        await dm_send_rate_limiter.acquire()
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.post(
                f"{self.base_url}/v1/dm/send",
                json={
                    "recipient_user_id": recipient_user_id,
                    "message": message,
                    "comment_id": comment_id,
                },
                headers=self._headers(idempotency_key),
            )

    async def get_dm_status(self, dm_id: str) -> httpx.Response:
        # Reads don't count against the rate limit per the README.
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await client.get(
                f"{self.base_url}/v1/dm/{dm_id}", headers=self._headers()
            )
