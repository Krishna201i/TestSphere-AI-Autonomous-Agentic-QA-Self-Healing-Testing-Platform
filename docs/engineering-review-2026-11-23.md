# TestSphere AI: verified safety and reliability improvements

Date: 23 November 2026. Target: existing `vinamra-branch`.
Starting remote HEAD: `5b8b0ea9a7f9c47cf4fcc5b91e31c723022f5a4a`.

This is an incremental engineering milestone, not completion of the entire
eleven-phase roadmap or a comprehensive security certification. Five code
changes were tested and published separately, with remote HEAD verification
after every change. This document is a separate documentation commit.

## Project assessment

The inspected branch already contains substantial functionality:

| Area | Verified implementation | Implication |
| --- | --- | --- |
| Orchestration | `backend/orchestration/orchestrator.py` configures the planner, analyzer, healing engine, feedback and bounded recovery policy; `backend/worker.py` uses conditional claims | Extend existing recovery and execution contracts rather than replacing them |
| Healing | `engine/healer.py` scores fingerprints, checks uniqueness/visibility, and rejects close competing fingerprint candidates; agent modules retain decisions and feedback | Existing evidence and ambiguity checks must remain intact |
| Memory | `agents/memory/persistent_store.py` persists records with an owner tag and replays a bounded history | Read isolation needs further attention: inherited indexes are keyed by test IDs/selectors, not owner/project |
| Planning | `agents/planner/prioritization.py` has deterministic ordering and explanations | Risk scheduling is an extension, not a missing foundational feature |
| Flakiness | `backend/pipeline/runner.py` counts result transitions; the dashboard displays flaky badges | Correct the evidence selection before adding prediction |
| Security patches | `security/patcher.py` handles Python frameworks, Express, nginx and dependency manifests, returns diffs and syntax results | Harden untrusted filesystem and scanner inputs; preserve disclosure evidence handling |
| Authentication/storage | `backend/auth.py` verifies Firebase/API tokens and exposes ownership filters; `backend/database/store.py` supports memory, local and Firestore stores | Database-backed and multi-user behavior require integration coverage |
| Visibility/frontend | Request tracing in `backend/observability.py`, pipeline stages, audit timeline, run detail and security review pages already exist | Use these events and real data for future dashboard additions |
| Delivery | Docker configuration and CI include lint, tests, build and security checks | CI push trigger currently names `main`; these branch pushes alone do not establish a successful CI run |

The first focused baseline (`tests/security` plus self-healing run tests) was
81 passed and 2 failed. Both failures were browser startup failures: the
installed Playwright expected Chromium headless shell revision 1255, which
was unavailable; its automatic download also failed. This was observed before
the production changes. No runtime performance bottleneck was measured, so
this milestone makes no performance claim.

An older local snapshot had unrelated uncommitted changes and was preserved.
Development used a clean checkout of the existing remote branch. No new
remote branch, merge, force push, migration or production deployment occurred.

## Changes and publication log

All five implementation commits were published sequentially on `vinamra-branch`
through the connected GitHub API. Each commit's tree matched the local staged
tree. Ref updates were non-forced and supplied the expected previous HEAD;
the branch was then read back and the local checkout fast-forwarded. All five
updates succeeded. Existing history and the earlier disclosure-string fix
were preserved.

| Order | Commit | Exact message | Files | Validation before publishing |
| --- | --- | --- | --- | --- |
| 1 | [016ab4f47bdb18ad7a17e117dc95b77f6b2ce296](https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform/commit/016ab4f47bdb18ad7a17e117dc95b77f6b2ce296) | `fix(security): exclude symlinks and special files from patch scans` | `security/patcher.py`, `tests/security/test_patcher.py` | 64 security tests passed; focused Ruff and diff checks passed |
| 2 | [cf788a4728e89989679e070e8b7444df55cbc260](https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform/commit/cf788a4728e89989679e070e8b7444df55cbc260) | `fix(security): validate dependency tokens before generating patches` | `security/patcher.py`, `tests/security/test_patcher.py` | 84 security/dependency tests passed; focused Ruff and diff checks passed |
| 3 | [8124347d11ca1a4ee1591b4cfe9542e27bf00e5f](https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform/commit/8124347d11ca1a4ee1591b4cfe9542e27bf00e5f) | `fix(security): scope npm version edits to dependency declarations` | `security/patcher.py`, `tests/security/test_patcher.py` | 98 security/dependency tests passed; focused Ruff and diff checks passed |
| 4 | [9fcfb6f92a1c73fa3790ea8ac1b7cdcdfe1f208c](https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform/commit/9fcfb6f92a1c73fa3790ea8ac1b7cdcdfe1f208c) | `fix(security): isolate malformed scanner findings during patch generation` | `security/patcher.py`, `tests/security/test_patcher.py` | 115 security/dependency tests passed; focused Ruff and diff checks passed |
| 5 | [bf5aced1726d8dd48791f36c5f19a3d2db9101cd](https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform/commit/bf5aced1726d8dd48791f36c5f19a3d2db9101cd) | `fix(pipeline): count only completed outcomes as flakiness evidence` | `backend/pipeline/runner.py`, `tests/backend/test_pipeline.py` | 64 pipeline/worker/self-healing tests passed, 2 browser tests deselected; focused Ruff and diff checks passed |

### 1. Repository scan boundary — phases 1 and 7

The scanner used `stat()`, which followed file symlinks, and accepted special
files. A symlink to outside source code could produce a patch containing that
source; opening a named pipe could block the scan.

Scanning now uses `lstat()` and accepts only regular files within the existing
size limit. Directory symlinks are explicitly pruned. Five regression cases
cover internal/external file links, dependency-manifest links, linked
directories/broken links, and a named pipe. Four cases failed before the fix.
Existing normal-file patch/apply tests continue to pass.

This does not provide a race-free sandbox against another process actively
replacing paths during the scan. Use a private, stable checkout for analysis.

### 2. Dependency evidence boundary — phases 1 and 7

Previously, a supplied fixed version containing a newline and an installer
option was inserted into `requirements.txt` and marked verified. Package
names and versions now require string tokens from conservative allowlists.
URLs, paths, markers, control characters, escape sequences and non-string
values produce manual-review results instead of edits.

Sixteen cases cover unsafe input and supported scoped package names,
prereleases, build metadata, epoch/post-release versions and version prefixes.
Twelve failed before the fix. These checks protect interpolation; they are
not full npm/PEP 440 validation, version comparison, or proof that an advisory
or recommended version is trustworthy.

### 3. JSON-aware manifest edits — phase 7

The previous regular expression searched the entire file after finding a
dependency, so a same-named `scripts` key could be modified instead. It also
updated only the first matching occurrence and crashed on non-object JSON.

The patcher now locates direct JSON value spans inside the four dependency
sections and replaces only supported version strings. It preserves unrelated
text and formatting and can update repeated declarations across sections.
It handles escaped keys, refuses duplicate keys in the objects it inspects,
and leaves aliases, URLs and compound ranges for manual review. The fallback
message now distinguishes possible absence, an unchanged version and an
unsupported specification instead of claiming every case is a missing package.

Fourteen cases cover section scope, all four dependency sections, idempotency,
actual `git apply`, malformed shapes, unsupported values, escaped names and
duplicate keys. Nine of the first twelve cases failed before the fix; the two
duplicate-key cases were added with the implementation.

### 4. Malformed scanner batches — phases 1 and 7

A bad record or wrongly typed text field could abort the entire patch request.
Invalid entries now produce an explicit manual-review result while valid
entries continue. Unidentifiable records use `INVALID-FINDING`; valid IDs are
preserved. Whitespace-only titles no longer cause an indexing exception.

All seventeen new regression cases failed before this change and pass after it.
The prior disclosure evidence handling for strings/lists remains intact.
The public input contract remains a list of findings; this is not an exhaustive
schema validator for every possible outer request shape.

### 5. Flakiness evidence — phase 3

Previously, `FAILED → RUNNING → FAILED` counted as two pass/fail transitions
and incorrectly earned a flaky badge. Only `PASSED`, `HEALED` and `FAILED`
now enter the outcome sequence. Other statuses are ignored. Existing handling
of healed passes, the history window and flip threshold are preserved.

Ten cases cover false-positive prevention and retention of real transitions
across ignored outcomes. Five failed before the fix. This remains a transition
heuristic; it does not yet distinguish application changes, infrastructure
failures and genuine nondeterminism or prove a test is flaky.

## Quality results

Counts below overlap and must not be added together.

| Check | Actual result / scope |
| --- | --- |
| Final security and dependency tests | 115 passed after all four patcher fixes |
| Broad Python run after patcher fixes | 1,524 passed, 16 skipped, 3 deselected; excludes `tests/engine` and `tests/e2e` and the three known browser-dependent backend tests |
| Subsequent flakiness fix | 64 passed, 2 deselected across pipeline, worker and self-healing run tests |
| Engine schemas and benchmark corpus structure | 31 passed; validates schemas and fixtures, not browser healing accuracy |
| Frontend | All 6 test files / 32 tests passed; production Vite build passed |
| Ruff | Repository-wide check passed after the five code changes |
| Earlier backend baseline | 374 passed, 16 skipped, 2 deselected, 1 failed; the failure was browser startup in the concurrent-session test |
| Browser-dependent failures observed | Two real-browser healing tests and one concurrency test could not launch the expected Chromium; these are not counted as passes |
| External-store coverage | PostgreSQL and Firestore emulator tests skipped without their configured services |
| Not executed | Full browser engine/E2E suites, browser healing benchmark, live-provider tests, dependency audit, container security scans, load/performance benchmarks |

The broader run covered the four patcher fixes; the fifth code change was
validated afterward with its focused regression set. Python emitted existing
test-collection/deprecation warnings. No tests or quality thresholds were
removed or weakened. No new dependencies, trained models, datasets, feature
flags, API shapes, database schema changes or frontend redesigns were added.

The test environment reused an installed Python environment and frontend
dependencies whose lockfile hash matched this branch; it was not a fresh
locked dependency installation. The frontend dependency link was removed
after verification. No benchmark improvement or ML accuracy claim is made.

### Reproduction

Use the development environment described in `CONTRIBUTING.md`, then run:

```bash
python -m pytest tests/security tests/test_dependency_vulns.py -q
python -m pytest tests/backend/test_pipeline.py tests/backend/test_worker.py tests/backend/test_self_healing_runs.py -q -k 'not TestRealBrowserHealing'
python -m pytest tests/engine/test_schemas.py tests/engine/test_heal_benchmark_corpus.py -q
python -m pytest tests/ -q --ignore=tests/e2e --ignore=tests/engine -k 'not TestRealBrowserHealing and not test_concurrent_browser_sessions_are_capped'
ruff check
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

With the required Chromium and external stores installed, run the full test
suite and healing benchmark before making release-level claims. Re-running
the broad command on the fifth commit includes ten additional pipeline cases.

## Remaining roadmap and limits

1. **Owner/project isolation in healing memory.** Persistent records carry
   owner tags, but the reviewed read indexes use selectors/test IDs and replay
   records across owners. First add two-owner/two-project collision tests,
   then enforce scope consistently in storage, loading and lookups. This is
   a concrete design concern; no end-to-end cross-user exploit was tested here.
2. **Dependency patch correctness.** Add ecosystem-aware version comparison,
   prevent downgrades, preserve upper bounds and environment markers, and
   regenerate lockfiles/hashes. Current syntax verification does not prove a
   proposed dependency set installs or resolves the advisory. Python manifest
   edits still need stronger structural handling.
3. **Complete browser validation.** Install the matching Playwright browser,
   run the engine/E2E suites and repeat the healing benchmark. Examine disabled
   elements and ambiguous fallback candidates without weakening existing gates.
4. **Explainable reliability signals.** Extend existing transition detection
   with revision, browser, retry and error-signature evidence and an
   insufficient-evidence state. Keep critical-test quarantine a reviewed action.
5. **Prioritization and observability.** Extend the existing priority scorer
   with opt-in normalized history/change signals and evaluate earlier regression
   discovery; enrich existing stage events rather than adding parallel systems.
6. **Measured performance and ML.** Profile first. Add ML only after collecting
   appropriately scoped labeled data and comparing against deterministic
   baselines. Keep resource usage practical for a 16 GB Apple Silicon laptop.

No configuration changes are required for these fixes. They intentionally
fail conservatively on unsafe/unsupported patch input. A rollback, if needed,
should be a new reviewed revert commit on this branch, preserving history;
reverting security checks restores the corresponding risks. Nothing in this
milestone authorizes deployment or merging into `main`.
