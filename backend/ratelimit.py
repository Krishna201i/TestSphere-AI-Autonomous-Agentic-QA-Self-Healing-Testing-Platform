"""
TestSphere-AI — Per-user rate limit for expensive actions.

Browser runs, scans, repository clones and LLM calls cost memory, time and
API quota, so each user may start ``RATE_LIMIT_RUNS_PER_MINUTE`` of them per
minute (sliding window, shared across those endpoints).  Over the limit the
request gets a 429 with ``Retry-After``.

Counts live in process memory: right for the single-instance deployment; a
multi-instance one needs a shared store.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, status

from backend.auth import User, get_current_user
from backend.config import settings

WINDOW_SECONDS = 60.0

_lock = threading.Lock()
_starts: dict[str, deque[float]] = defaultdict(deque)


def reset() -> None:
    """Forget all counts (tests)."""
    with _lock:
        _starts.clear()


def limit_runs(user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency: the caller, if they are under their run budget."""
    budget = settings.RATE_LIMIT_RUNS_PER_MINUTE
    if budget <= 0:
        return user
    now = time.monotonic()
    with _lock:
        starts = _starts[user.uid]
        while starts and now - starts[0] >= WINDOW_SECONDS:
            starts.popleft()
        if len(starts) >= budget:
            retry_after = max(1, int(WINDOW_SECONDS - (now - starts[0])) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many runs: at most {budget} per minute. Try again in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )
        starts.append(now)
    return user
