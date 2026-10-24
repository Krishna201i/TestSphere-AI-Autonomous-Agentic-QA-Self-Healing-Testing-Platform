# TestSphere AI — Member 2: Browser Engine, Self-Healing & Security Testing

**Owner:** Krishna Singh · **Branch:** `krishna-branch` · **Main folders:** [`engine/`](engine/),
[`security/`](security/), [`ingestion/`](ingestion/), [`scripts/`](scripts/)

This branch contains the whole TestSphere AI project. This README covers the part Member 2 owns: the
Playwright engine that runs the tests and heals broken locators, the security scanner and fix patcher, and the
code ingestion. For the overview of the whole platform, see the [README on `main`](../../tree/main#readme).

---

## What this part does

- **Runs the tests.** The engine runs each test case in Chromium, captures a screenshot, a DOM snapshot and a
  Playwright trace per test, and runs several browsers at once within a fixed number of slots.
- **Heals broken locators.** When a locator stops matching, the engine tries the stored fallbacks first, then
  a fingerprint scan of the live DOM. It scores attributes, text, position and structure, and refuses
  look-alikes and elements whose kind changed.
- **Guards the browser.** Every request the test browser makes goes through an egress guard, so a tested page
  cannot reach private or internal addresses.
- **Scans for security weaknesses.** A passive, scope-checked scanner checks headers, cookies, CORS, TLS,
  forms and information disclosure. It sends one GET per page and no payloads.
- **Writes fixes.** The fix patcher turns header, CORS and cookie findings into a patch against the app's own
  code (FastAPI, Flask, Django, Express, nginx) and checks that the patched files still compile.
- **Reads the codebase.** Ingestion builds a blueprint of a repository (languages, frameworks, dependencies,
  routes, test suites, committed secrets, debug flags) without running any of its code.

## Modules

| Module | Contents |
| --- | --- |
| [`engine/runner.py`](engine/runner.py), [`engine/browser.py`](engine/browser.py) | Test execution, browser sessions and slots |
| [`engine/locators.py`](engine/locators.py), [`engine/healer.py`](engine/healer.py), [`engine/detector.py`](engine/detector.py) | Locator resolution, breakage detection, self-healing |
| [`engine/egress.py`](engine/egress.py) | Outbound request guard for the browser |
| [`engine/artifacts.py`](engine/artifacts.py) | Screenshots, DOM snapshots, traces |
| [`engine/heal_benchmark.py`](engine/heal_benchmark.py), [`engine/benchmark.py`](engine/benchmark.py) | Self-healing benchmark and engine benchmark |
| [`security/passive_scanner.py`](security/passive_scanner.py), [`security/scope.py`](security/scope.py) | Passive scanner and scope checks |
| [`security/remediation.py`](security/remediation.py), [`security/patcher.py`](security/patcher.py) | Fix proposals and fix patches |
| [`ingestion/`](ingestion/) | Repository source handling and static analysis |
| [`scripts/loadtest.py`](scripts/loadtest.py) | API and pipeline load test |

## Results this part contributes

| Measurement | Result |
| --- | --- |
| Self-healing benchmark, 277 cases ([report](docs/healing-benchmark.md)) | **95.2%** healed where healing is right, **0 false heals**; a static fallback chain heals 96.1% but 17.4% of its heals hit the wrong element |
| Live sites (the-internet, saucedemo, practicetestautomation, TodoMVC) | 4 of 4 run the written goal and pass |
| Fix patches on real repositories (FastAPI, Express and Django RealWorld apps, microblog, Flask) | 5 of 5 apply to a fresh clone and compile |
| Load ([report](docs/load-test.md)) | ~600–700 requests/s on one worker; 8 pipeline runs at once in 27 s |

## Working on this part

```bash
pip install -e ".[dev]"
python -m playwright install chromium

python -m pytest tests/engine tests/security tests/test_ingestion.py -q   # engine, scanner, patcher, ingestion
python -m engine.heal_benchmark --quick                                  # healing benchmark (drop --quick for all cases)
python -m security http://127.0.0.1:8000/                                # passive scan of a local app
python scripts/loadtest.py                                               # load test against a running API
```

Only scan sites you own or have permission to test. Hosted scans are limited to `SECURITY_SCAN_ALLOWED_HOSTS`.

Documentation: [Browser execution engine](docs/engine-architecture.md) ·
[Self-healing & orchestration](docs/self-healing-orchestration.md) · [Healing benchmark](docs/healing-benchmark.md) ·
[Load test](docs/load-test.md)

## How work reaches `main`

1. Branch from `krishna-branch` or work on it directly.
2. Keep the engine and security tests passing, and re-run the healing benchmark after changing healing.
3. Open a pull request into `main`. CI runs the full test suite, the security scans and the frontend build.
