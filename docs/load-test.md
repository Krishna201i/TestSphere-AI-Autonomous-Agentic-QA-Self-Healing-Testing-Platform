# Load test

Measured with `python scripts/loadtest.py` on Windows 10, 16 CPU threads, 16.4 GB RAM; one uvicorn worker, local JSON store, sign-in off, ENGINE_MAX_BROWSERS=2. Hosted servers are slower per core; treat these as upper bounds and keep headroom.

## Dashboard API

Each client repeats the calls a dashboard tab makes (9 endpoints) for 15 s.

| Concurrent clients | Requests/s | p50 | p95 | p99 | Errors |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 699 | 0 ms | 16 ms | 16 ms | 0 |
| 10 | 679 | 16 ms | 31 ms | 32 ms | 0 |
| 50 | 660 | 78 ms | 94 ms | 156 ms | 0 |
| 100 | 615 | 157 ms | 250 ms | 312 ms | 0 |

## Pipeline runs started together

Each run: page analysis, 3–4 generated browser tests, self-healing and a passive security scan on a local site.

| Runs at once | All finished after | Median run | Passed | Peak memory (server + Chromium) |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3 s | 3 s | 1/1 | 222 MB |
| 2 | 7 s | 5 s | 2/2 | 462 MB |
| 4 | 13 s | 9 s | 4/4 | 457 MB |
| 8 | 27 s | 15 s | 8/8 | 462 MB |

Idle server memory: 112 MB.

## Sizing

- Browser runs dominate memory: each Chromium instance adds roughly the difference between the 1-run and idle rows above. `ENGINE_MAX_BROWSERS` caps how many run at once; further runs queue instead of exhausting memory, so the server stays responsive.
- 512 MB instances can hold the API and one browser at most; use at least 1 GB with `ENGINE_MAX_BROWSERS=1`, or 2 GB with the default of 2. For more parallel runs, move them to the worker (`PIPELINE_EXECUTION=worker`) and size the worker, not the API.
