"""Brute-force limits (ТЗ SEC-02 п.3, NIST 800-63B §3.2.2).

Three independent sliding windows: (account, source), source, whole service. Limits only ever
impose a *temporary* wait, so an attacker can slow down sign-in for a victim's account from
their own address but cannot lock the victim out permanently or from the victim's own network.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

WINDOW = 15 * 60
LIMITS = {
    'pair': (5, 60),        # 5 failures for (email, source) in 15 min -> wait up to 60 s, doubling
    'source': (30, 300),    # 30 failures from one address -> wait 5 min
    'global': (300, 30),    # 300 failures on the whole service per 15 min -> everyone waits 30 s
}
MAX_PAIR_WAIT = 15 * 60


class Throttle:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.failures: dict[tuple, deque] = defaultdict(deque)

    def _recent(self, key, now):
        q = self.failures[key]
        while q and now - q[0] > WINDOW:
            q.popleft()
        return q

    def wait_seconds(self, email: str, source: str) -> int:
        """0 when an attempt may proceed now, otherwise seconds to wait (never unbounded)."""
        now = self.clock()
        email = (email or '').strip().casefold()
        with self.lock:
            waits = []
            pair = self._recent(('pair', email, source), now)
            limit, base = LIMITS['pair']
            if len(pair) >= limit:
                extra = len(pair) - limit
                waits.append(min(MAX_PAIR_WAIT, base * (2 ** extra)) - (now - pair[-1]))
            src = self._recent(('source', source), now)
            if len(src) >= LIMITS['source'][0]:
                waits.append(LIMITS['source'][1] - (now - src[-1]))
            glob = self._recent(('global',), now)
            if len(glob) >= LIMITS['global'][0]:
                waits.append(LIMITS['global'][1] - (now - glob[-1]))
        return max(0, int(max(waits, default=0)) + (1 if waits and max(waits) > 0 else 0))

    def failure(self, email: str, source: str):
        now = self.clock()
        email = (email or '').strip().casefold()
        with self.lock:
            for key in (('pair', email, source), ('source', source), ('global',)):
                self._recent(key, now).append(now)

    def success(self, email: str, source: str):
        with self.lock:
            self.failures.pop(('pair', (email or '').strip().casefold(), source), None)


DEFAULT = Throttle()
