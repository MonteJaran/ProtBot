"""
ratelimit.py - A simple per-key rate limiter for the two link endpoints.

server/models.py note 4 names this directly: "the audit's other half of
this finding — rate-limiting the link-code endpoint — is still open;
nothing in the client can substitute for that." An 8-character key
(core/linking.py's KEY_ALPHABET is 32 characters, minus the four people
misread) is about 1.1e12 combinations — safe against one guess, not
against an unthrottled script making thousands of guesses a minute before
a 5-minute key expires.

In-memory, per-process: resets on restart, and does not share state across
multiple server instances behind a load balancer. Documented rather than
hidden, the same posture as core/syncproto.py's own known-imperfect notes
— a single-instance deployment (what STATUS.md's "an afternoon" / "a day"
estimates describe) is the realistic first target, and a distributed
limiter is real scope this does not need yet.
"""

import time
from collections import defaultdict, deque


class RateLimiter:
    """A sliding-window log: at most `max_requests` calls to allow() per
    `key` in any trailing `window_sec` seconds."""

    def __init__(self, max_requests: int, window_sec: float) -> None:
        self.max_requests = max_requests
        self.window_sec = window_sec
        self._hits: dict = defaultdict(deque)

    def allow(self, key: str, now=None) -> bool:
        """
        Whether `key` may proceed right now. Every call — allowed or not —
        records an attempt, which is what makes this a log rather than a
        counter: a burst of denied calls still ages out of the window on
        its own, with nothing special to reset.
        """
        moment = now if now is not None else time.time()
        hits = self._hits[key]
        cutoff = moment - self.window_sec

        while hits and hits[0] < cutoff:
            hits.popleft()

        hits.append(moment)
        return len(hits) <= self.max_requests
