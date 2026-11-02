"""
TestSphere-AI — Worker liveness file (``python -m backend.worker_alive``).

The worker touches ``WORKER_ALIVE_FILE`` on every loop pass and heartbeat.
Run as a module, this exits 1 once the file is older than
``WORKER_STALE_SECONDS``: the worker container's health check.  Kept free of
imports so the check costs milliseconds, not a pipeline import.
"""

import contextlib
import os
import sys
import tempfile
import time

STALE_SECONDS = float(os.getenv("WORKER_STALE_SECONDS", "600"))
ALIVE_FILE = os.getenv("WORKER_ALIVE_FILE", os.path.join(tempfile.gettempdir(), "testsphere-worker-alive"))


def touch() -> None:
    with contextlib.suppress(OSError):
        with open(ALIVE_FILE, "a"):
            pass
        os.utime(ALIVE_FILE)


def is_alive(now: float | None = None) -> bool:
    """Whether this machine's worker touched the file within STALE_SECONDS."""
    try:
        return (now or time.time()) - os.path.getmtime(ALIVE_FILE) < STALE_SECONDS
    except OSError:
        return False


if __name__ == "__main__":
    sys.exit(0 if is_alive() else 1)
