"""
Load test: how much the TestSphere server handles, to size the instance.

    python scripts/loadtest.py                  # full: API reads + concurrent pipeline runs
    python scripts/loadtest.py --api-only       # just the dashboard API

It starts its own backend (local JSON store, sign-in off, inline pipeline runs)
and a small target site, then measures:

1. Dashboard API under load: the requests a dashboard tab makes (health,
   projects, executions, findings, audit, runs) from N concurrent clients for
   a fixed time each — requests per second, p50/p95/p99 latency, errors.
2. Pipeline runs started at the same time (1, 2, 4, 8): wall time until all
   finish, per-run time, and the server's peak memory including its Chromium
   processes (psutil, if installed).

Writes docs/load-test.md.  Numbers are for the machine it runs on; the report
records that machine's CPU count and memory.
"""

from __future__ import annotations

import argparse
import asyncio
import http.server
import os
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

try:
    import psutil
except ImportError:  # memory is reported only when psutil is available
    psutil = None

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_CALLS = ["/api/health", "/api/projects", "/api/test-executions?limit=200", "/api/test-executions/stats",
                   "/api/security/findings", "/api/audit?limit=300", "/api/pipelines/runs?limit=40",
                   "/api/pipelines/deployments?limit=10", "/api/system"]
SITE_HTML = """<!doctype html><html><head><title>Load shop</title></head><body>
<h1>Welcome back</h1><form onsubmit="return false"><input id="email" name="email" placeholder="Email"/>
<input id="password" name="password" type="password" placeholder="Password"/>
<button id="login" type="button">Log in</button></form><a href="/about.html">About</a></body></html>"""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_site(root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    (root / "index.html").write_text(SITE_HTML, encoding="utf-8")
    (root / "about.html").write_text("<!doctype html><title>About</title><h1>About</h1>", encoding="utf-8")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def log_message(self, *a):
            pass

    port = free_port()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{port}/"


class Backend:
    def __init__(self, workdir: Path) -> None:
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        env = {**os.environ, "DATABASE_BACKEND": "local", "AUTH_REQUIRED": "false", "SCHEDULER_ENABLED": "false",
               "LOCAL_DB_PATH": str(workdir / "db.json"), "ARTIFACTS_DIR": str(workdir / "artifacts"),
               "INGEST_WORKSPACE": str(workdir / "repos"), "LOG_FORMAT": "text", "LOG_LEVEL": "WARNING",
               "RATE_LIMIT_RUNS_PER_MINUTE": "0", "PIPELINE_EXECUTION": "inline", "ARTIFACT_TRACES": "false"}
        self.proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "backend.main:app", "--port", str(self.port)],
                                     cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(120):
            try:
                if httpx.get(f"{self.base}/api/health", timeout=1).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.5)
        raise RuntimeError("backend did not start")

    def rss_mb(self) -> float | None:
        """Server plus children (Chromium) resident memory."""
        if psutil is None:
            return None
        try:
            p = psutil.Process(self.proc.pid)
            procs = [p, *p.children(recursive=True)]
            return sum(x.memory_info().rss for x in procs if x.is_running()) / 1e6
        except psutil.Error:
            return None

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(q * (len(values) - 1))))]


def api_level(base: str, clients: int, seconds: float) -> dict:
    """Threads with keep-alive connections, like browsers.  (An asyncio httpx
    client saturates on Windows long before the server does: 3 req/s at 50
    clients against a bare hello-world app, which serves 6,500 req/s this way.)"""
    import concurrent.futures
    import http.client
    from urllib.parse import urlsplit

    host, port = urlsplit(base).hostname, urlsplit(base).port
    latencies: list[float] = []
    errors = 0
    lock = threading.Lock()
    stop = time.monotonic() + seconds

    def client(i: int) -> None:
        nonlocal errors
        conn = http.client.HTTPConnection(host, port, timeout=30)
        mine: list[float] = []
        bad = 0
        n = i
        while time.monotonic() < stop:
            path = DASHBOARD_CALLS[n % len(DASHBOARD_CALLS)]
            n += 1
            started = time.monotonic()
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                resp.read()
                bad += resp.status >= 400
            except (OSError, http.client.HTTPException):
                bad += 1
                conn.close()
                conn = http.client.HTTPConnection(host, port, timeout=30)
            mine.append((time.monotonic() - started) * 1000)
        conn.close()
        with lock:
            latencies.extend(mine)
            errors += bad

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(clients) as pool:
        list(pool.map(client, range(clients)))
    elapsed = time.monotonic() - started
    return {"clients": clients, "requests": len(latencies), "rps": len(latencies) / elapsed, "errors": errors,
            "p50": pct(latencies, 0.5), "p95": pct(latencies, 0.95), "p99": pct(latencies, 0.99)}


async def seed(base: str, site: str, runs: int = 1) -> None:
    """Give the API realistic data: a project with finished runs and findings."""
    async with httpx.AsyncClient(base_url=base, timeout=600) as c:
        await c.post("/api/security/scan", json={"url": site})
        for _ in range(runs):
            run = (await c.post("/api/pipelines/quick", json={"url": site})).json()
            while (await c.get(f"/api/pipelines/runs/{run['id']}")).json()["status"] in ("queued", "running"):
                await asyncio.sleep(1)


async def runs_level(backend: Backend, site: str, count: int) -> dict:
    peak = backend.rss_mb() or 0.0
    async with httpx.AsyncClient(base_url=backend.base, timeout=60) as c:
        started = time.monotonic()
        ids = []
        for i in range(count):
            # one project per run: runs of the same project are serialized by design
            r = await c.post("/api/pipelines/quick", json={"url": f"{site}?load={count}-{i}"})
            ids.append(r.json()["id"])
        done: dict[int, float] = {}
        statuses: dict[int, str] = {}
        while len(done) < count:
            await asyncio.sleep(1)
            peak = max(peak, backend.rss_mb() or 0.0)
            for rid in ids:
                if rid in done:
                    continue
                run = (await c.get(f"/api/pipelines/runs/{rid}")).json()
                if run["status"] not in ("queued", "running"):
                    done[rid] = time.monotonic() - started
                    statuses[rid] = run["status"]
            if time.monotonic() - started > 1800:
                break
    times = list(done.values())
    return {"runs": count, "wall_s": max(times) if times else None, "median_run_s": statistics.median(times) if times else None,
            "ok": sum(1 for s in statuses.values() if s == "passed"), "peak_mb": round(peak) if peak else None}


def report(api: list[dict], runs: list[dict], idle_mb: float | None, seconds: float) -> Path:
    mem = f"{psutil.virtual_memory().total / 1e9:.1f} GB RAM" if psutil else "RAM unknown (psutil not installed)"
    lines = [
        "# Load test",
        "",
        f"Measured with `python scripts/loadtest.py` on {platform.system()} {platform.release()}, "
        f"{os.cpu_count()} CPU threads, {mem}; one uvicorn worker, local JSON store, sign-in off, "
        f"ENGINE_MAX_BROWSERS={os.getenv('ENGINE_MAX_BROWSERS', '2')}. "
        "Hosted servers are slower per core; treat these as upper bounds and keep headroom.",
        "",
        "## Dashboard API",
        "",
        f"Each client repeats the calls a dashboard tab makes ({len(DASHBOARD_CALLS)} endpoints) for {seconds:.0f} s.",
        "",
        "| Concurrent clients | Requests/s | p50 | p95 | p99 | Errors |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for a in api:
        lines.append(f"| {a['clients']} | {a['rps']:.0f} | {a['p50']:.0f} ms | {a['p95']:.0f} ms | {a['p99']:.0f} ms | {a['errors']} |")
    if runs:
        lines += ["", "## Pipeline runs started together", "",
                  "Each run: page analysis, 3–4 generated browser tests, self-healing and a passive security scan on a local site.",
                  "", "| Runs at once | All finished after | Median run | Passed | Peak memory (server + Chromium) |",
                  "| ---: | ---: | ---: | ---: | ---: |"]
        for r in runs:
            lines.append(f"| {r['runs']} | {r['wall_s']:.0f} s | {r['median_run_s']:.0f} s | {r['ok']}/{r['runs']} | "
                         + (f"{r['peak_mb']} MB |" if r["peak_mb"] else "— |"))
        if idle_mb:
            lines += ["", f"Idle server memory: {idle_mb:.0f} MB."]
    lines += ["", "## Sizing", "",
              "- Browser runs dominate memory: each Chromium instance adds roughly the difference between the 1-run and "
              "idle rows above. `ENGINE_MAX_BROWSERS` caps how many run at once; further runs queue instead of "
              "exhausting memory, so the server stays responsive.",
              "- 512 MB instances can hold the API and one browser at most; use at least 1 GB with "
              "`ENGINE_MAX_BROWSERS=1`, or 2 GB with the default of 2. For more parallel runs, move them to the "
              "worker (`PIPELINE_EXECUTION=worker`) and size the worker, not the API.",
              ""]
    path = ROOT / "docs" / "load-test.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--clients", type=int, nargs="*", default=[1, 10, 50, 100])
    parser.add_argument("--runs", type=int, nargs="*", default=[1, 2, 4, 8])
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="loadtest-"))
    site_server, site = serve_site(workdir)
    backend = Backend(workdir)
    try:
        print("seeding data (one scan, one pipeline run)...", flush=True)
        await seed(backend.base, site)
        idle = backend.rss_mb()
        api = []
        for n in args.clients:
            res = await asyncio.to_thread(api_level, backend.base, n, args.seconds)
            print(f"API {n:>3} clients: {res['rps']:.0f} req/s  p95 {res['p95']:.0f} ms  errors {res['errors']}", flush=True)
            api.append(res)
        runs = []
        if not args.api_only:
            for k in args.runs:
                res = await runs_level(backend, site, k)
                print(f"{k} runs at once: all done in {res['wall_s']:.0f}s, peak {res['peak_mb']} MB", flush=True)
                runs.append(res)
        path = report(api, runs, idle, args.seconds)
        print(f"Wrote {path}")
    finally:
        backend.stop()
        site_server.shutdown()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
