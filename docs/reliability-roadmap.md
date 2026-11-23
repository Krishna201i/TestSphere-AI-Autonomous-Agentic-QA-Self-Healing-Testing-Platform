# TestSphere AI: Incremental Reliability Roadmap

This is a proposed roadmap, not evidence that the features below already exist.
All work targets `VinamraBhatnagar` and must preserve existing API contracts,
project data, healing safety gates, frontend routes and operational behavior.

## Verified starting point

- FastAPI backend, React/Vite frontend, Playwright engine, agent planner,
  explorer, analyzer, healer, orchestration, model fallback and memory.
- Human approval/rejection for self-heals, tests generated from plain English,
  Playwright import, passive and authorized active security scanning.
- Existing CI runs Python tests, frontend tests/build, healing accuracy gates,
  Test Studio accuracy gates, security scans and Docker smoke checks.
- The repository documents 277 healing benchmark cases, 19 bug-detection
  cases, and a separate generation evaluation. Re-run before citing numbers
  as current results; don't promise unverified improvements.

## Change policy

1. Start from current remote branch HEAD; never reset, force-push, rebase, or
   modify teammates' branches without explicit approval.
2. Inspect existing code and tests before calling any feature missing.
3. Add a failing test for a real bug or regression scenario, then fix it.
4. Keep public API contracts backward-compatible. New features must be
   behind additive opt-in flags, with disabled-by-default behavior.
5. Run focused tests plus CI gates; when full tests are unavailable, report
   exactly which dependency or service blocked them.
6. Commit logically complete changes using `fix:`, `test:`, `feat:`,
   `docs:`, `refactor:` or `chore:`. No filler commits.
7. Never commit credentials, user data, traces, screenshots with secrets,
   local encryption keys, model artifacts or generated dependencies.

## P0: preserve trust first

- Document and test local key-file permissions, concurrent startup and
  key reuse; hosted environments must continue to require a configured key.
- Audit every browser URL, redirects, outbound network request and repository
  clone path for scope enforcement and SSRF, preserving existing guardrails.
- Verify that heal rejection, review and write-back are atomic and auditable;
  never silently mark a healed test as a clean pass.
- Add regression test matrices for browser crashes, queue retries, model
  timeouts, storage unavailability and webhook replay.

## P1: reliability intelligence

- Start with deterministic flaky-test scoring from repeat-run evidence.
  Distinguish product defects, infrastructure failures, timing races and
  inconclusive runs; do not automatically quarantine critical failures.
- Group similar failures using normalized error signatures and shared stack
  locations; preserve raw evidence for human review.
- Add opt-in risk-based execution order using changed-file relevance,
  historical failure frequency, business impact and flaky risk. Log weights
  and feature contributions. Never claim learned weights before evaluation.
- Expose heal candidate signals, alternatives, threshold, ambiguity margin
  and rejection reason without disclosing page secrets.
- Keep the existing healing benchmark gate at least as strict as it is today.

## P2: observability and user experience

- Build a read-only agent decision timeline from existing pipeline events:
  stage, timestamp, evidence, decision, cost estimate, retry, fallback.
- Provide trends for pass rate, confirmed regressions, false-heal rate,
  time-to-diagnosis, model cost and human-review outcomes.
- Label unknown or incomplete metrics explicitly; don't fabricate counts.
- Expose accessibility-friendly controls and test both themes/mobile layouts.

## P3: research-grade improvement

- Create a sanitized, deterministic offline evaluation dataset from
  consenting test fixtures rather than raw user site content.
- Compare heuristics with optionally trained ranking/classification models:
  precision/recall, false-heal rate, false-negative rate, calibration,
  runtime and cost. Include leakage checks and held-out applications.
- Persist evidence only within the existing user's project boundary.
  Add retention, deletion and opt-out controls before collecting new data.
- Keep a non-LLM path so local development can run without paid API keys.

## Release acceptance

- Existing behavior remains unchanged when new flags are disabled.
- No unauthorized network requests; no direct changes to customer apps.
- No dropped tests, migration failures, broken imports, secret exposure,
  false-heal benchmark regression, or broken dashboard workflows.
- New features have documented API shape, migration behavior, tests,
  reproducible benchmark method and rollback instructions.
