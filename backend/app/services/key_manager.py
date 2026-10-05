"""Gemini API key pool with round-robin + error-driven rotation.

Keys come from the ``GEMINI_API_KEYS`` env var (comma separated), then from
the legacy single ``GEMINI_API_KEY``, then from the bundled backup list.
A key that hits a quota or auth error is parked in cooldown and the pool
switches to the next key immediately, so one dead key never stalls the
extraction pipeline.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger(__name__)

COOLDOWN_SECONDS = 65.0

DEFAULT_KEYS: tuple[str, ...] = (
    "REDACTED-GEMINI-KEY",
    "REDACTED-GEMINI-KEY",
    "REDACTED-GEMINI-KEY",
    "REDACTED-GEMINI-KEY",
    "REDACTED-GEMINI-KEY",
    "REDACTED-GEMINI-KEY",
    "REDACTED-GEMINI-KEY",
    "REDACTED-GEMINI-KEY",
    "REDACTED-GEMINI-KEY",
    "REDACTED-GEMINI-KEY",
)


def _load_keys() -> list[str]:
    """Resolve the key pool from settings, falling back to the defaults."""
    try:
        from app.config import settings

        raw = (settings.gemini_api_keys or "").strip()
        if raw:
            keys = [k.strip() for k in raw.split(",") if k.strip()]
            if keys:
                return keys
        single = (settings.gemini_api_key or "").strip()
        if single:
            return [single]
    except Exception:  # noqa: BLE001
        logger.exception("Could not read keys from settings; using bundled defaults")
    return list(DEFAULT_KEYS)


class GeminiKeyPool:
    """Thread-safe round-robin pool with a per-key cooldown."""

    def __init__(self, keys: list[str] | None = None) -> None:
        self._keys = list(keys) if keys else _load_keys()
        self._index = 0
        self._cooldown_until = [0.0] * len(self._keys)
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        return len(self._keys)

    def current_key(self) -> str:
        """Return the active key, skipping any key still in cooldown."""
        with self._lock:
            now = time.monotonic()
            for _ in range(len(self._keys)):
                if self._cooldown_until[self._index] <= now:
                    return self._keys[self._index]
                self._index = (self._index + 1) % len(self._keys)
            return self._keys[self._index]

    def get_current_key(self) -> str:
        """Alias required by the assessment spec."""
        return self.current_key()

    def rotate(self, exc: BaseException | None = None) -> str:
        """Cool down the active key (if given an error) and return the next."""
        with self._lock:
            if exc is not None:
                self._cooldown_until[self._index] = time.monotonic() + COOLDOWN_SECONDS
                logger.warning(
                    "Key ...%s failed (%s); cooling down for %ds",
                    self._keys[self._index][-4:],
                    type(exc).__name__,
                    int(COOLDOWN_SECONDS),
                )
            self._index = (self._index + 1) % len(self._keys)
            return self._keys[self._index]

    def configure(self) -> str:
        """Apply the active key through ``genai.configure`` and return it."""
        import google.generativeai as genai

        key = self.current_key()
        genai.configure(api_key=key)
        return key


_pool: GeminiKeyPool | None = None
_pool_lock = threading.Lock()


def get_pool() -> GeminiKeyPool:
    """Process-wide singleton pool."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = GeminiKeyPool()
            logger.info("Gemini key pool initialised with %d key(s)", _pool.size)
        return _pool


def reset_pool(keys: list[str] | None = None) -> GeminiKeyPool:
    """Replace the pool (used by tests and by the key-rotation endpoint)."""
    global _pool
    with _pool_lock:
        _pool = GeminiKeyPool(keys)
        return _pool


def get_current_key() -> str:
    return get_pool().get_current_key()


def get_active_client() -> str:
    """Configure and return the active key (spec-compatible helper)."""
    return get_pool().configure()


def is_quota_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    return "429" in text or "quota" in text or "exhaust" in text or "resourceexhausted" in name


def is_auth_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    name = type(exc).__name__.lower()
    return (
        "401" in text
        or "403" in text
        or "unauthenticated" in text
        or "permissiondenied" in name
        or ("invalid" in text and "key" in text)
    )


def is_recoverable_with_next_key(exc: BaseException) -> bool:
    """Quota and auth failures are worth retrying on another key."""
    return is_quota_error(exc) or is_auth_error(exc)
