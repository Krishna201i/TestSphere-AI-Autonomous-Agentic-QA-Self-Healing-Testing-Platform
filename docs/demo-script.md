# Demo script: TestSphere AI in 10 minutes

A walkthrough that shows each word of "Autonomous Agentic QA & Self-Healing Testing Platform" working, on a site
whose code you control so you can break it on purpose. Every step uses the real product; nothing is mocked.

## Before you start (5 minutes, once)

1. **A site you can change.** The simplest is the small login site the tests use:

   ```bash
   cd backend
   python -c "from tests.fixtures.auth_app import AuthApp; import time; print(AuthApp().start() + '/login'); time.sleep(10**6)"
   ```

   It prints a URL such as `http://127.0.0.1:53412/login` (user `demo@testsphere.test`, password `Correct-Horse-7`).
   Locally, private addresses are allowed (`APP_ENV=development`). On the hosted server use a public site you own.
2. **The platform.** `cd backend && python -m uvicorn app.main:app --port 8000` and `cd frontend && npm run dev`,
   or the hosted dashboard. For the AI parts set `LLM_PROVIDER=chain` and at least one provider key; without one,
   the rule-based planner answers (and says so).

## 1. Autonomous (2 minutes)

1. **Projects → Run pipeline** on the site URL with the goal
   `log in with demo@testsphere.test / Correct-Horse-7`.
2. On the **Dashboard**, watch the pipeline stages light up live with the timer running, the **Live run** card
   fill with real screenshots, and the **AI agents** panel show which agent is active.
3. **Schedules:** set the project to run hourly. Point out that a GitHub push webhook does the same on every commit.

## 2. Agentic: Test Studio (3 minutes)

1. **AI Agents → Test Studio → Suggest from my code**: the flows most worth testing, ranked by risk.
2. Type: *"Log in with demo@testsphere.test and password Wrong-Pass-123 and check an error message is shown."*
   → **Write the steps**. Each step shows how it finds its element (on the page / by text at run time).
3. **Save test**, then **Run**: it passes. Show **.spec.ts** export: a real Playwright file.
4. **Import Playwright tests**: upload any `*.spec.ts`; lines it cannot read (a helper, `process.env`) are listed,
   never guessed.

## 3. QA (1 minute)

Open the run (**Test Runs**): every test with steps, screenshots, the Playwright trace, and why a failure happened.
Open **Security**: findings from the passive scan, ranked; a fix becomes a pull request in one click.
**Reports → PDF**: the shareable report.

## 4. Self-Healing (2 minutes), the centrepiece

1. Break the site the way a front-end change does: in your own app (or a copy of a page served with
   `python -m http.server`), rename the `id`, `data-testid` or class of a button a saved test clicks.
   The repository's test `backend/tests/app/test_test_studio_browser.py` does exactly this, if you want to see it
   scripted.
2. Run the pipeline again. The test that clicked the button is **HEALED**, not failed, and the run says which
   locator replaced which, with the strategy and confidence.
3. Open **Self-Healing**: the heal with its screenshot. **Approve** it: the test now uses the new locator.
4. Show the other direction: **Reject** a heal and run again. The test now **fails** with "a reviewer rejected
   healing this step", because a heal a person said is wrong can never pass a test.

## 5. Platform (1 minute)

Sign in with Google or GitHub (each account sees only its own data), switch to dark mode, open the dashboard on a
phone, and show **Integrations** (GitHub, API tokens for coding agents via the MCP server).

## The numbers to close with

- Self-healing: **95.7%** of 277 broken locators healed with **0 false heals** ([report](healing-benchmark.md)).
- Plain-English tests: **18 of 19** real bugs caught with **0 false alarms** ([report](studio-eval.md)).
- Both are gates in CI: a change that adds one false heal or false alarm cannot merge.
