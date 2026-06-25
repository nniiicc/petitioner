"""HTTP transport — owns the network, pacing, retries, and the session recipe.

Encapsulates the verified access recipe: warm a ``_change_session`` cookie from the
csrf endpoint, then POST GraphQL with the ``x-requested-with`` client header. No
other layer issues HTTP. On PerimeterX bot challenge it HALTS (raises) rather than
attempting any defeat (spec §8.4).
"""

from __future__ import annotations

import random
import time
from types import TracebackType
from typing import Any

import httpx
import orjson
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from . import adapter
from .config import Settings

log = structlog.get_logger(__name__)


class TransportError(Exception):
    """Non-retryable transport-layer failure."""


class BotChallengeError(TransportError):
    """PerimeterX/CAPTCHA challenge encountered — halt and surface (spec §8.4)."""


class InvalidClientError(TransportError):
    """api-proxy rejected the client header — adapter/config drift, not a bot block."""


class _RateLimiter:
    """Minimum-interval pacer with additive jitter (spec §5.7)."""

    def __init__(self, rps: float, jitter: float) -> None:
        self._min_interval = 1.0 / rps
        self._jitter = jitter
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        target = self._last + self._min_interval + random.uniform(0, self._jitter)
        if target > now:
            time.sleep(target - now)
        self._last = time.monotonic()


def _is_bot_challenge(resp: httpx.Response) -> bool:
    """Heuristic for a PerimeterX block (distinct from a normal 4xx)."""
    if resp.status_code in (403, 429):
        body = resp.text[:2000].lower()
        markers = (
            "px-captcha",
            "perimeterx",
            "_px",
            "access to this page has been denied",
            "blockscript",
            "captcha",
        )
        if any(m in body for m in markers):
            return True
        # PX often sets a fresh _px* cookie on the challenge response.
        if any(c.lower().startswith("_px") for c in resp.cookies):
            return True
    return False


class Transport:
    """A pooled httpx client carrying the authenticated-free session."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._limiter = _RateLimiter(
            settings.requests_per_second, settings.jitter_seconds
        )
        self._request_count = 0
        self._csrf_token: str | None = None
        self._client = httpx.Client(
            timeout=settings.request_timeout_seconds,
            headers={
                "user-agent": settings.user_agent,
                "x-requested-with": adapter.X_REQUESTED_WITH,
                "accept": "application/json",
                "origin": adapter.BASE_URL,
                "referer": f"{adapter.BASE_URL}/",
            },
            follow_redirects=True,
        )

    # -- lifecycle ---------------------------------------------------------- #
    def __enter__(self) -> Transport:
        self.warm_session()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # -- internals ---------------------------------------------------------- #
    def _check_ceiling(self) -> None:
        self._request_count += 1
        if self._request_count > self._settings.per_domain_request_ceiling:
            raise TransportError(
                f"per-domain request ceiling reached "
                f"({self._settings.per_domain_request_ceiling})"
            )

    def warm_session(self) -> None:
        """GET the csrf endpoint to set the ``_change_session`` cookie."""
        self._limiter.wait()
        self._check_ceiling()
        resp = self._client.get(f"{adapter.CSRF_URL}?cb={int(time.time())}000")
        if _is_bot_challenge(resp):
            raise BotChallengeError("bot challenge during session warm-up")
        self._csrf_token = resp.headers.get("x-csrf-token")
        log.debug("session_warmed", has_csrf=bool(self._csrf_token))

    # -- GraphQL ------------------------------------------------------------ #
    def post_graphql(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST a GraphQL body and return parsed JSON. Retries transient failures."""

        @retry(
            retry=retry_if_exception_type(
                (httpx.TransportError, httpx.HTTPStatusError)
            ),
            wait=wait_exponential(multiplier=self._settings.backoff_base_seconds),
            stop=stop_after_attempt(self._settings.max_retries + 1),
            reraise=True,
        )
        def _do() -> httpx.Response:
            self._limiter.wait()
            self._check_ceiling()
            headers = {}
            if self._csrf_token:
                headers["x-csrf-token"] = self._csrf_token
            op = body.get("operationName", "Q")
            resp = self._client.post(
                f"{adapter.GRAPHQL_URL}?op={op}",
                content=orjson.dumps(body),
                headers={**headers, "content-type": "application/json"},
            )
            if _is_bot_challenge(resp):
                raise BotChallengeError("bot challenge on GraphQL request")
            if resp.status_code >= 500 or resp.status_code == 429:
                resp.raise_for_status()
            return resp

        resp = _do()
        if resp.status_code == 400 and "invalid client" in resp.text.lower():
            raise InvalidClientError(resp.text[:200])
        try:
            return orjson.loads(resp.content)  # type: ignore[no-any-return]
        except orjson.JSONDecodeError as exc:
            raise TransportError(
                f"non-JSON GraphQL response: {resp.text[:200]}"
            ) from exc

    def get_text(self, url: str) -> str:
        """Fetch a plain-text resource (e.g. sitemaps), paced and ceiling-checked."""
        self._limiter.wait()
        self._check_ceiling()
        resp = self._client.get(url)
        if _is_bot_challenge(resp):
            raise BotChallengeError(f"bot challenge fetching {url}")
        resp.raise_for_status()
        return resp.text
