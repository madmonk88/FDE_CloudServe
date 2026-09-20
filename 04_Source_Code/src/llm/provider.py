"""Model access, with the failure handling that acceptance criterion A11 asks
for built into the client rather than sprinkled around its callers.

Four things sit between the rest of the system and the provider:

1. A content-addressed cache. The same prompt returns the same answer without
   a network call. This protects the free-tier allowance, makes a full run
   reproducible, and is what makes A5 (same input, same routing decision)
   true in practice rather than only in principle.
2. A self-imposed rate limit. Free tiers throttle. Pacing ourselves is
   cheaper than being throttled halfway through a 120-ticket run.
3. Retries with exponential backoff and jitter, on the errors that are worth
   retrying and not on the ones that are not.
4. A circuit breaker. After a run of consecutive failures the client stops
   calling the provider altogether for a cooldown period and raises
   ProviderUnavailable immediately. Every caller has a deterministic fallback
   for that exception, so the system degrades to reduced capability rather
   than stopping. This is the behaviour the build spec explicitly says gains
   credit rather than losing it.

The interface is OpenAI-compatible, which covers both providers the brief
names. Swapping between them is an environment variable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)


class ProviderUnavailable(RuntimeError):
    """The model provider could not be reached or refused to serve.

    Callers must catch this and continue on a deterministic path. It is not an
    error condition for the run; it is an expected operating mode.
    """


class ProviderRefused(RuntimeError):
    """The provider answered, but with something unusable (bad key, bad model).

    Distinguished from ProviderUnavailable because retrying will not help.
    """


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class ResponseCache:
    """A cache on disk, keyed by the hash of everything that affects the answer.

    Keyed on model, temperature and the full message list, so changing any of
    them correctly misses rather than silently returning a stale answer.
    """

    def __init__(self, directory: Path, enabled: bool = True) -> None:
        self.directory = Path(directory)
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        if self.enabled:
            self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(model: str, temperature: float, messages: list[dict[str, str]]) -> str:
        payload = json.dumps(
            {"model": model, "temperature": temperature, "messages": messages},
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        # Two-character shard so the directory stays usable with 10k entries.
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str) -> str | None:
        if not self.enabled:
            return None
        path = self._path(key)
        if not path.exists():
            with self._lock:
                self.misses += 1
            return None
        try:
            with self._lock:
                self.hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["content"]
        except Exception:
            return None

    def put(self, key: str, content: str) -> None:
        if not self.enabled:
            return
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps({"content": content, "cached_at": time.time()}),
                encoding="utf-8",
            )
            tmp.replace(path)
        except Exception as exc:  # pragma: no cover - cache is best effort
            log.debug("cache write failed: %s", exc)

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class RateLimiter:
    """A sliding-window limiter. Blocks rather than failing, because the point
    is to pace the run, not to abandon tickets."""

    def __init__(self, requests_per_minute: int) -> None:
        self.rpm = max(1, requests_per_minute)
        self._times: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._times and now - self._times[0] > 60.0:
                    self._times.popleft()
                if len(self._times) < self.rpm:
                    self._times.append(now)
                    return
                wait = 60.0 - (now - self._times[0]) + 0.05
            time.sleep(min(wait, 60.0))


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    def __init__(self, threshold: int, cooldown: float) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self.opened_at is None:
                return False
            if time.monotonic() - self.opened_at >= self.cooldown:
                # Half-open: allow one probe through.
                self.opened_at = None
                self.failures = 0
                log.info("circuit breaker cooled down; probing provider again")
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self.failures = 0
            self.opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.failures >= self.threshold and self.opened_at is None:
                self.opened_at = time.monotonic()
                log.warning(
                    "circuit breaker opened after %d consecutive failures; "
                    "running on the deterministic fallback path for %.0fs",
                    self.failures,
                    self.cooldown,
                )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class LLMClient:
    """The only place in the system that talks to a model provider."""

    def __init__(self, settings: Any | None = None) -> None:
        s = settings or get_settings()
        self.cfg = s.model
        self.cache = ResponseCache(s.paths.llm_cache_dir, self.cfg.cache_enabled)
        self.limiter = RateLimiter(self.cfg.requests_per_minute)
        self.breaker = CircuitBreaker(
            self.cfg.circuit_breaker_threshold, self.cfg.circuit_breaker_cooldown
        )
        self.calls = 0
        self.failures = 0
        self._client: httpx.Client | None = None

    # -- lifecycle ---------------------------------------------------------

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.cfg.base_url.rstrip("/"),
                timeout=httpx.Timeout(self.cfg.timeout_seconds),
                headers={
                    "Authorization": f"Bearer {self.cfg.api_key}",
                    "Content-Type": "application/json",
                    # OpenRouter asks for these; harmless elsewhere.
                    "HTTP-Referer": "https://github.com/cloudserve-support",
                    "X-Title": "CloudServe Support Intelligence",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    @property
    def available(self) -> bool:
        return bool(self.cfg.api_key) and not self.breaker.is_open

    # -- the call ----------------------------------------------------------

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """Return the model's text, or raise ProviderUnavailable.

        Never returns a partial or invented answer on failure. Callers decide
        what to do without a model; this function's only job is to be honest
        about whether it got one.
        """
        temperature = self.cfg.temperature if temperature is None else temperature
        max_tokens = self.cfg.max_tokens if max_tokens is None else max_tokens

        cache_key = ResponseCache.key(self.cfg.model, temperature, messages)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        if not self.cfg.api_key:
            raise ProviderUnavailable(
                "no API key configured; running on the deterministic fallback path"
            )
        if self.breaker.is_open:
            raise ProviderUnavailable("circuit breaker open")

        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Seed does not guarantee determinism on every provider, but where
            # it is honoured it helps, and where it is not it is ignored.
            "seed": 20250913,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_error: Exception | None = None

        for attempt in range(self.cfg.max_retries):
            self.limiter.acquire()
            try:
                self.calls += 1
                response = self._http().post("/chat/completions", json=payload)

                if response.status_code in _RETRYABLE_STATUS:
                    retry_after = response.headers.get("retry-after")
                    asked = None
                    if retry_after and retry_after.replace(".", "").isdigit():
                        asked = float(retry_after)

                    # A Retry-After longer than the cap is not a pause, it is a
                    # refusal with a timestamp on it. Free tiers answer a
                    # daily quota exhaustion with hundreds of seconds, and
                    # sleeping through that blocks the run for hours while
                    # looking like progress — a full evaluation was observed
                    # stalling on waits of 215s, 403s and 541s in sequence.
                    #
                    # The right behaviour is the one A11 asks for: stop
                    # waiting, open the circuit, and let the system degrade to
                    # its deterministic path so the run completes with reduced
                    # capability instead of not completing at all. The cached
                    # work is kept, so a later --resume picks up cheaply once
                    # the quota resets.
                    if asked is not None and asked > self.cfg.max_retry_after:
                        self.breaker.record_failure()
                        log.warning(
                            "provider asked for a %.0fs wait, above the %.0fs cap — "
                            "treating as unavailable and degrading rather than "
                            "stalling the run",
                            asked,
                            self.cfg.max_retry_after,
                        )
                        raise ProviderUnavailable(
                            f"rate limited; provider asked for {asked:.0f}s, "
                            f"above the {self.cfg.max_retry_after:.0f}s cap"
                        )

                    delay = asked if asked is not None else self._backoff(attempt)
                    delay = min(delay, self.cfg.max_retry_after)
                    last_error = ProviderUnavailable(
                        f"provider returned {response.status_code}"
                    )
                    log.warning(
                        "provider %s on attempt %d; waiting %.1fs",
                        response.status_code,
                        attempt + 1,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                if response.status_code in (401, 403):
                    self.breaker.record_failure()
                    raise ProviderRefused(
                        f"provider rejected the credentials ({response.status_code}). "
                        "Check OPENROUTER_API_KEY."
                    )

                if response.status_code >= 400:
                    self.breaker.record_failure()
                    raise ProviderRefused(
                        f"provider returned {response.status_code}: {response.text[:300]}"
                    )

                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    last_error = ProviderUnavailable("provider returned no choices")
                    time.sleep(self._backoff(attempt))
                    continue

                content = (choices[0].get("message") or {}).get("content") or ""
                if not content.strip():
                    last_error = ProviderUnavailable("provider returned empty content")
                    time.sleep(self._backoff(attempt))
                    continue

                self.breaker.record_success()
                self.cache.put(cache_key, content)
                return content

            except ProviderRefused:
                raise
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPError) as exc:
                last_error = exc
                self.failures += 1
                delay = self._backoff(attempt)
                log.warning(
                    "provider transport error on attempt %d (%s); waiting %.1fs",
                    attempt + 1,
                    type(exc).__name__,
                    delay,
                )
                time.sleep(delay)
            except Exception as exc:  # pragma: no cover - defensive
                last_error = exc
                self.failures += 1
                time.sleep(self._backoff(attempt))

        self.breaker.record_failure()
        raise ProviderUnavailable(
            f"provider unreachable after {self.cfg.max_retries} attempts: {last_error}"
        )

    @staticmethod
    def _backoff(attempt: int) -> float:
        """Exponential with jitter, capped. Jitter matters when a run recovers
        from an outage: without it every queued request retries in lockstep and
        re-triggers the throttle that caused the outage."""
        base = min(2.0 ** attempt, 16.0)
        return base + random.uniform(0.0, 0.75)

    # -- reporting ---------------------------------------------------------

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "transport_failures": self.failures,
            "cache": self.cache.stats,
            "circuit_open": self.breaker.is_open,
            "model": self.cfg.model,
        }


_client: LLMClient | None = None


def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def reset_client() -> None:
    """Used by tests that need a client built from changed settings."""
    global _client
    if _client is not None:
        _client.close()
    _client = None
