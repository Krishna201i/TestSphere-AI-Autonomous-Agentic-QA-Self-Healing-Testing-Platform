"""
TestSphere-AI — Per-user rate limit for expensive actions.

Browser runs, scans, repository clones and LLM calls cost memory, time and
API quota, so each user may start ``RATE_LIMIT_RUNS_PER_MINUTE`` of them per
minute (sliding window, shared across those endpoints).  Over the limit the
request gets a 429 with ``Retry-After``.

Counts live in process memory by default, right for one instance.  With
``RATE_LIMIT_BACKEND=database`` they live in the store instead, one row of
recent start times per user, updated by compare-and-set, so several
instances share one budget.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, status

from backend.auth import User, get_current_user
from backend.config import settings
from backend.database.session import get_db
from backend.database.store import Store
from backend.models import RATE_LIMITS

WINDOW_SECONDS = 60.0

_lock = threading.Lock()
_starts: dict[str, deque[float]] = defaultdict(deque)


def reset() -> None:
    """Forget all counts (tests)."""
    with _lock:
        _starts.clear()


def _too_many(budget: int, retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many runs: at most {budget} per minute. Try again in {retry_after}s.",
        headers={"Retry-After": str(retry_after)},
    )


def _limit_in_store(db: Store, uid: str, budget: int) -> None:
    """The shared budget: recent start times in one row per user, written
    only if no other instance changed them since they were read."""
    for _ in range(5):
        now = time.time()
        row = db.find_one(RATE_LIMITS, owner_uid=uid) or db.insert(RATE_LIMITS, owner_uid=uid, starts=[])
        recent = [t for t in row.get("starts") or [] if now - t < WINDOW_SECONDS]
        if len(recent) >= budget:
            raise _too_many(budget, max(1, int(WINDOW_SECONDS - (now - min(recent))) + 1))
        if db.update_if(RATE_LIMITS, row["id"], "starts", row.get("starts"), starts=[*recent, now]):
            return
    raise _too_many(budget, 1)  # contended by many concurrent starts: ask to retry shortly


def limit_runs(user: User = Depends(get_current_user), db: Store = Depends(get_db)) -> User:
    """FastAPI dependency: the caller, if they are under their run budget."""
    budget = settings.RATE_LIMIT_RUNS_PER_MINUTE
    if budget <= 0:
        return user
    if settings.RATE_LIMIT_BACKEND == "database":
        _limit_in_store(db, user.uid, budget)
        return user
    now = time.monotonic()
    with _lock:
        starts = _starts[user.uid]
        while starts and now - starts[0] >= WINDOW_SECONDS:
            starts.popleft()
        if len(starts) >= budget:
            raise _too_many(budget, max(1, int(WINDOW_SECONDS - (now - starts[0])) + 1))
        starts.append(now)
    return user
