"""Login / auth rate limiting (SEC-02): per account, per source, global.

Never permanently lock a victim account from a single attacker IP.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

_LOCK = threading.Lock()
_BY_ACCOUNT: dict[str, deque] = defaultdict(deque)
_BY_SOURCE: dict[str, deque] = defaultdict(deque)
_GLOBAL: deque = deque()

ACCOUNT_LIMIT = 8
ACCOUNT_WINDOW = 900  # 15 min
SOURCE_LIMIT = 30
SOURCE_WINDOW = 900
GLOBAL_LIMIT = 200
GLOBAL_WINDOW = 900
# Soft lockout delay after failures (seconds), not permanent ban
BACKOFF_STEPS = (0, 1, 2, 5, 10, 20, 30)


def _prune(q: deque, window: float, now: float) -> None:
    while q and now - q[0] >= window:
        q.popleft()


def allow_login_attempt(account_key: str, source: str) -> tuple[bool, float]:
    """Return (allowed, retry_after_seconds)."""
    now = time.monotonic()
    account_key = (account_key or '').strip().lower() or '_'
    source = (source or '').strip() or '_'
    with _LOCK:
        aq = _BY_ACCOUNT[account_key]
        sq = _BY_SOURCE[source]
        _prune(aq, ACCOUNT_WINDOW, now)
        _prune(sq, SOURCE_WINDOW, now)
        _prune(_GLOBAL, GLOBAL_WINDOW, now)
        if len(aq) >= ACCOUNT_LIMIT:
            return False, ACCOUNT_WINDOW
        if len(sq) >= SOURCE_LIMIT:
            return False, SOURCE_WINDOW
        if len(_GLOBAL) >= GLOBAL_LIMIT:
            return False, GLOBAL_WINDOW
        failures = len(aq)
        delay = BACKOFF_STEPS[min(failures, len(BACKOFF_STEPS) - 1)]
        return True, float(delay)


def register_failure(account_key: str, source: str) -> None:
    now = time.monotonic()
    with _LOCK:
        _BY_ACCOUNT[(account_key or '').strip().lower() or '_'].append(now)
        _BY_SOURCE[(source or '').strip() or '_'].append(now)
        _GLOBAL.append(now)


def register_success(account_key: str) -> None:
    with _LOCK:
        _BY_ACCOUNT.pop((account_key or '').strip().lower() or '_', None)


def reset_for_tests() -> None:
    with _LOCK:
        _BY_ACCOUNT.clear()
        _BY_SOURCE.clear()
        _GLOBAL.clear()
