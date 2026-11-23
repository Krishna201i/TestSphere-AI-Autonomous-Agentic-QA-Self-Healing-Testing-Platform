<div align="center">

<img src="docs/assets/banner.svg" alt="TestSphere AI — Autonomous Agentic QA &amp; Self-Healing Testing Platform" width="100%"/>

<br/>

[![CI](https://img.shields.io/github/actions/workflow/status/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform/ci.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI&labelColor=17402c&color=2a6a46)](https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11+-17402c?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Playwright](https://img.shields.io/badge/Engine-Playwright-2a6a46?style=for-the-badge&logo=playwright&logoColor=white)](https://playwright.dev/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-17402c?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/Dashboard-React-2a6a46?style=for-the-badge&logo=react&logoColor=white)](https://react.dev/)
[![Firebase](https://img.shields.io/badge/Auth%20%26%20DB-Firebase-17402c?style=for-the-badge&logo=firebase&logoColor=white)](https://firebase.google.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-2a6a46?style=for-the-badge)](LICENSE)

<br/>

**[Overview](#-what-is-testsphere-ai)** ·
**[Screenshots](#-take-a-tour)** ·
**[The loop](#-the-testing-loop)** ·
**[Self-healing](#-self-healing-broken-tests-repair-themselves-correctly)** ·
**[Security](#-security-the-attacker-agent)** ·
**[Architecture](#-architecture)** ·
**[Results](#-measured-results)** ·
**[Get started](#-getting-started)** ·
**[Docs](#-documentation)**

</div>

<br/>

---

## ✨ What is TestSphere AI?

> **Give it a URL.** Optionally add a goal in plain words and a Git repository. TestSphere AI reads the code, plans browser tests, runs them in Chromium, **repairs broken locators while the test runs**, scans the site for security weaknesses, and turns fixable findings into a **patch or a pull request**. Each fix is retested, a verified version can be deployed with **automatic rollback**, and the whole loop runs again on a schedule or on every push.

<table>
<tr>
<td width="25%" valign="top">

### 🤖 Autonomous
Runs on a **schedule**, on every **git push**, or from one click. No one has to start it.

</td>
<td width="25%" valign="top">

### 🧠 Agentic
Planner, Explorer, Failure Analyzer, Healer and Attacker agents on a **fallback chain of LLMs**.

</td>
<td width="25%" valign="top">

### 🩹 Self-healing
Repairs broken locators correctly, and **refuses** look-alikes. **0 false heals** in the benchmark.

</td>
<td width="25%" valign="top">

### 🛡️ Secure by design
SSRF guard on every request. Page text reaches the AI only as **fenced, untrusted data**.

</td>
</tr>
</table>

Write your own tests in plain English in **Test Studio** (or import your Playwright tests), review every heal on the **Self-Healing** page, and let the AI agents run on a fallback chain of models, largest context window first (Gemini, NVIDIA Nemotron, NVIDIA Gemma, Groq). Full platform breakdown: [platform overview](docs/platform-overview.md).

<br/>

<div align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/screenshots/dashboard-dark.png">
  <img src="docs/assets/screenshots/dashboard-light.png" alt="TestSphere AI dashboard — latest run, step by step" width="92%"/>
</picture>
<br/><br/>
<sub><b>The dashboard</b> — your latest run, step by step, what to do next. Follows your OS light/dark theme.</sub>
</div>

<br/>

## 📊 At a glance

<div align="center">
<img src="docs/assets/results-gauges.svg" alt="95.7% locators healed · 18/19 bugs caught · 52/52 security checks · 8/8 concurrent runs" width="100%"/>
</div>

<br/>

<details>
<summary><b>📑 Table of contents</b></summary>
<br/>

- [What is TestSphere AI?](#-what-is-testsphere-ai)
- [Take a tour](#-take-a-tour)
- [The testing loop](#-the-testing-loop)
- [Test Studio — tests in plain English](#-test-studio-tests-in-plain-english)
- [Self-healing](#-self-healing-broken-tests-repair-themselves-correctly)
- [Security: the attacker agent](#-security-the-attacker-agent)
- [AI agents and the LLM fallback chain](#-ai-agents-and-the-llm-fallback-chain)
- [Architecture](#-architecture)
- [Measured results](#-measured-results)
- [Getting started](#-getting-started)
- [Configuration and deployment](#-configuration-and-deployment)
- [Tech stack](#-tech-stack)
- [Documentation](#-documentation)
- [Security and privacy](#-security-and-privacy)
- [Team](#-team)

</details>

---

## 🖼️ Take a tour

<table>
<tr>
<td width="50%" valign="top">
<a href="docs/assets/screenshots/projects-light.png">
<img src="docs/assets/screenshots/projects-light.png" alt="Projects page"/>
</a>

#### 🗂️ Projects
Point at a URL, optionally a repo and a plain-English goal. Pick what to generate, run once or on a schedule.
</td>
<td width="50%" valign="top">
<a href="docs/assets/screenshots/test-studio-light.png">
<img src="docs/assets/screenshots/test-studio-light.png" alt="Test Studio"/>
</a>

#### 🎯 Test Studio
Describe a test in plain English. Every step is verified against your live page before anything runs.
</td>
</tr>
<tr>
<td width="50%" valign="top">
<a href="docs/assets/screenshots/run-detail-light.png">
<img src="docs/assets/screenshots/run-detail-light.png" alt="Run detail — PASSED"/>
</a>

#### 🧾 Run report
A plain-language verdict, every pipeline stage, PDF and JUnit export, and a read-only share link that expires.
</td>
<td width="50%" valign="top">
<a href="docs/assets/screenshots/run-detail-tests-light.png">
<img src="docs/assets/screenshots/run-detail-tests-light.png" alt="Run detail — test list"/>
</a>

#### 📋 Test breakdown
Every test with its steps, screenshots, Playwright trace, failure reason and self-heal details.
</td>
</tr>
<tr>
<td width="50%" valign="top">
<a href="docs/assets/screenshots/security-light.png">
<img src="docs/assets/screenshots/security-light.png" alt="Security — attacker agent"/>
</a>

#### 🛡️ Security
Findings with proof levels and an exposure radar. Fix patches open a PR in one click.
</td>
<td width="50%" valign="top">
<a href="docs/assets/screenshots/self-healing-light.png">
<img src="docs/assets/screenshots/self-healing-light.png" alt="Self-Healing review"/>
</a>

#### 🩹 Self-Healing review
Approve a heal to keep it, reject one that reached the wrong element. A rejected step can never pass again.
</td>
</tr>
<tr>
<td width="50%" valign="top">
<a href="docs/assets/screenshots/overview-light.png">
<img src="docs/assets/screenshots/overview-light.png" alt="Overview — trends and stats"/>
</a>

#### 📈 Overview
Pass rate, flaky tests, regressions and trends across every run of every project.
</td>
<td width="50%" valign="top">
<a href="docs/assets/screenshots/ai-agents-light.png">
<img src="docs/assets/screenshots/ai-agents-light.png" alt="AI agents page"/>
</a>

#### 🤖 AI agents
Which agent is active, which model answered, and how the LLM fallback chain is performing.
</td>
</tr>
</table>

<details>
<summary><b>🌗 Dark mode · 📱 Phone layout · More pages</b></summary>
<br/>

**Dark mode (every page, WCAG 2.1 AA):**

<table>
<tr>
<td width="50%"><img src="docs/assets/screenshots/dashboard-dark.png" alt="Dashboard dark"/><br/><sub>Dashboard</sub></td>
<td width="50%"><img src="docs/assets/screenshots/security-dark.png" alt="Security dark"/><br/><sub>Security — Attacker Agent</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/assets/screenshots/test-runs-dark.png" alt="Test runs dark"/><br/><sub>Test Runs</sub></td>
<td width="50%"><img src="docs/assets/screenshots/overview-dark.png" alt="Overview dark"/><br/><sub>Overview — Insights</sub></td>
</tr>
</table>

**Phone layout:**

<div align="center">
<img src="docs/assets/screenshots/mobile-light.png" alt="Dashboard on a phone" width="300"/>
</div>

<br/>

**More pages:**

<table>
<tr>
<td width="50%"><img src="docs/assets/screenshots/pipeline-light.png" alt="Pipeline visualizer"/><br/><sub><b>Pipeline</b> — the loop, live, with timers</sub></td>
<td width="50%"><img src="docs/assets/screenshots/reports-light.png" alt="Reports"/><br/><sub><b>Reports</b> — PDF and JUnit export</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/assets/screenshots/integrations-light.png" alt="Integrations"/><br/><sub><b>Integrations</b> — GitHub · GitLab · Bitbucket · Slack · MCP</sub></td>
<td width="50%"><img src="docs/assets/screenshots/schedules-light.png" alt="Schedules"/><br/><sub><b>Schedules</b> — every 15 min to weekly</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/assets/screenshots/audit-log-light.png" alt="Audit log"/><br/><sub><b>Audit log</b> — every action, recorded</sub></td>
<td width="50%"><img src="docs/assets/screenshots/settings-light.png" alt="Settings"/><br/><sub><b>Settings</b> — theme, profile, privacy, delete account</sub></td>
</tr>
</table>

</details>

---

## 🔁 The testing loop

<div align="center">
<img src="docs/assets/pipeline-loop.svg" alt="The TestSphere AI pipeline loop: ingest → QA agent → attacker agent → report + remediation → validation → verified deploy" width="100%"/>
</div>

<br/>

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#e4f1e8','primaryBorderColor':'#2a6a46','primaryTextColor':'#17402c','lineColor':'#2a6a46','secondaryColor':'#fbf0d4','tertiaryColor':'#fbfaf7'}}}%%
flowchart LR
    U(["🌐 URL + goal\n+ repo (optional)"]) --> I["1 · Ingest\nblueprint"]
    I --> Q["2A · QA agent\nplan + run + heal"]
    I --> A["2B · Attacker agent\nscope-checked scan"]
    Q --> R["3 · Unified report"]
    A --> R
    R --> F["4 · AI remediation\npatch / PR"]
    F --> H{{"👤 Human\napproval"}}
    H -->|approved| V["5 · Validation\nretest"]
    V -->|still failing| F
    V -->|passes| D["6 · Verified deploy\nhealth + smoke"]
    D -->|unhealthy| RB(["↩️ Auto rollback"])
    D -->|healthy| OK(["✅ Shipped"])
    OK -. "schedule / git push" .-> U
    classDef good fill:#e4f1e8,stroke:#2a6a46,color:#17402c
    classDef warn fill:#fbe6da,stroke:#c2531a,color:#7a2e0e
    classDef human fill:#e4ecfa,stroke:#2f62bd,color:#1d3f73
    class OK,Q,I,V,D good
    class A,RB warn
    class H human
```

| Stage | What it does |
| --- | --- |
| **1. Codebase ingestion** | Clones a public repository (or reads a local folder in development) and builds a blueprint: languages, frameworks, dependencies, existing test suites, HTTP routes, committed secrets and debug flags. Reads its Playwright tests, which every run then replays as saved tests. Nothing in the repository is executed on the server. |
| **2A. AI QA agent** | Analyzes the live page (rendering JS apps in a real browser), turns the written goal into steps, plans smoke / scenario / content / linked-page tests, and runs them in Playwright. With a real model, an AI explorer reaches the goal in a live browser once, records the steps as a reusable test, and writes negative tests for every validated form (empty required fields, malformed email). Every new test is then run on a deliberately broken copy of its page; one that still passes is marked as checking nothing — coverage is never overstated. |
| **Test Studio** | Write a test in plain English (*"log in as demo / secret, add the backpack to the cart, check the cart shows 1"*). The AI model (or the rule-based planner without one) turns it into steps from a fixed vocabulary, and every step is checked against the live page before anything runs. Review and edit the steps, save the test, run it, or export it as a Playwright `.spec.ts`. Saved tests run in every pipeline run and self-heal like the rest. |
| **Repository tests** | Reports the repository's own unit tests: CI results on the run's commit (GitHub), or a sandboxed run (pytest, npm test, go test) with no network access and no access to the server or its secrets. Failing tests fail the run. |
| **Self-healing** | When a locator breaks, the engine tries stored fallbacks, then a fingerprint scan of the live DOM (scoring attributes, text, position, structure). It refuses look-alikes and elements whose kind changed. |
| **2B. Attacker agent** | Scope-checked security scan. Passive by default (headers, cookies, CORS, TLS, forms, information disclosure — one GET per page, no payloads). Optional active (DAST) mode sends reflected-XSS, SQL-injection and open-redirect probes to apps you own, confirmed by running each XSS payload in a real browser. AI triage prioritizes findings and drafts a fix — reasoning only over findings already in scope. |
| **3. Unified report** | Test results, regressions since the previous run, flaky tests and security findings in one report, with screenshots, DOM snapshots and Playwright traces for every test. Every failure says why it happened and what to do next. Downloads as PDF or shares via a read-only link that expires. |
| **4. AI remediation** | Findings become syntax-checked fix patches against the app's own code (FastAPI, Flask, Django, Express, Next.js, nginx). Approving one opens a pull request on GitHub/Bitbucket, or a merge request on GitLab — nothing changes in the repository until then. |
| **5. Validation engine** | Re-runs the original check after a fix; findings resolve or reopen as regressions. |
| **6. Verified deploy** | Calls the deploy hook (Render, Vercel, Netlify, or a GitHub Actions workflow), waits for the new version to be healthy, runs smoke tests, and rolls back automatically if either fails. |

**Around the loop:** scheduled runs, GitHub push webhooks, commit statuses, Slack alerts, JUnit XML export, quarantine for known-bad tests, an audit trail, sign-in with per-user data isolation, and a live dashboard.

### What happens inside a single run

```mermaid
%%{init: {'theme':'base','themeVariables':{'actorBkg':'#17402c','actorTextColor':'#ffffff','actorBorder':'#17402c','signalColor':'#2a6a46','noteBkgColor':'#fbf0d4','noteTextColor':'#5c4300','activationBkgColor':'#e4f1e8'}}}%%
sequenceDiagram
    autonumber
    actor You as 👤 You / git push / schedule
    participant API as FastAPI pipeline runner
    participant Ing as Ingestion
    participant AI as AI agents
    participant Eng as Playwright engine
    participant Sec as Attacker agent
    participant Site as 🌐 Your web app
    participant Git as GitHub / GitLab

    You->>API: Run pipeline (URL, goal, repo)
    API->>Ing: Read repository (never executed)
    Ing-->>API: Blueprint: routes, tests, secrets
    API->>AI: Plan tests from page + goal + blueprint
    AI-->>API: Test plan (every element verified on page)
    API->>Eng: Execute tests in Chromium
    loop every test
        Eng->>Site: Click, type, assert
        alt locator broke
            Eng->>Eng: Heal — fallbacks → fingerprint → AI healer
            Note over Eng: Reported as HEALED, never silently as passed
        end
        Eng-->>API: Result + screenshot + DOM + trace
    end
    API->>Sec: Scan (scope-checked allowlist)
    Sec->>Site: Passive GETs · opt-in DAST probes
    Sec-->>API: Findings + AI triage
    API-->>You: Report · PDF · JUnit · Slack · commit status
    You->>API: Approve fix patch
    API->>Git: Open pull request
    API->>Eng: Retest the fix
    Eng-->>API: Resolved or reopened as regression
```

---

## 🎯 Test Studio: tests in plain English

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#e4f1e8','primaryBorderColor':'#2a6a46','primaryTextColor':'#17402c','lineColor':'#2a6a46'}}}%%
flowchart LR
    T["✍️ Plain-English instruction\n'Log in as demo / secret,\nadd the backpack to the cart,\ncheck the cart shows 1'"] --> P["🧠 Planner\nLLM or rule-based"]
    P --> S["📋 Steps from a\nfixed vocabulary"]
    S --> V{"🔎 Verify each step\nagainst the live page"}
    V -->|on the page| OK["✅ Trusted"]
    V -->|found by text at run time| OK
    V -->|not seen| Q["⚠️ Quarantined\nuntil you trust it"]
    OK --> R["👀 Review & edit"]
    Q --> R
    R --> SV["💾 Save test"]
    SV --> RUN["▶️ Runs in every pipeline\n(self-heals like the rest)"]
    SV --> X["📤 Export Playwright .spec.ts"]
    IMP["📥 Import .spec.ts\n(read as text, never executed)"] --> SV
    classDef n fill:#e4f1e8,stroke:#2a6a46,color:#17402c
    classDef w fill:#fbf0d4,stroke:#d99a1f,color:#5c4300
    class OK,RUN,X,SV,R n
    class Q w
```

**Key features:**
- **Suggest from my code** — ranks the user flows most worth testing from the repository's routes and the live page.
- **Import Playwright tests** — lines the importer cannot read (a helper, `process.env`) are listed, never guessed.
- **Honesty built in** — a test that cannot fail is flagged, an AI-written test is quarantined until trusted, and any part of a goal that could not be tested says so.

---

## 🩹 Self-healing: broken tests repair themselves, correctly

A front-end refactor renames an `id` and the test suite goes red. TestSphere finds the *same* element again — and **refuses to heal when the right answer is "this element is gone"**.

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#e4f1e8','primaryBorderColor':'#2a6a46','primaryTextColor':'#17402c','lineColor':'#2a6a46'}}}%%
flowchart TD
    B(["💥 Locator no longer matches"]) --> L["1 · Learned fallbacks\nhealing memory"]
    L -->|unique match| C
    L -->|none| F["2 · Fingerprint scan of the live DOM\nattributes · text · position · structure"]
    F -->|confident| C
    F -->|unsure| AI["3 · AI Healer proposes a candidate"]
    AI -->|re-run passes| C
    AI -->|re-run fails| X
    F -->|look-alike, or element's kind changed| X(["⛔ Refuse — fail honestly"])
    C(["✅ HEALED\nwritten back to the test\nreported as HEALED, never as passed"]) --> RV{"👤 Heal review"}
    RV -->|Approve| KEEP(["Locator kept permanently"])
    RV -->|Reject| BAD(["Step can no longer heal\nnext run FAILS — never passes\non the wrong element"])
    classDef good fill:#e4f1e8,stroke:#2a6a46,color:#17402c
    classDef bad fill:#fbe6da,stroke:#c2531a,color:#7a2e0e
    classDef human fill:#e4ecfa,stroke:#2f62bd,color:#1d3f73
    class C,KEEP good
    class X,BAD bad
    class RV human
```

### Benchmark: 277 broken-locator cases

<div align="center">
<img src="docs/assets/healing-benchmark.svg" alt="Healing benchmark: TestSphere heals 95.7% with 0 false heals; a static fallback chain heals 96.1% but 17.4% hit the wrong element" width="100%"/>
</div>

<br/>

<table>
<tr>
<td width="50%" valign="top">

**TestSphere healer — 277 cases**

```mermaid
%%{init: {'theme':'base','themeVariables':{'pie1':'#2a6a46','pie2':'#9fcbb0','pie3':'#d99a1f'}}}%%
pie showData
    title TestSphere: 277 cases
    "Healed correctly" : 198
    "Correctly refused" : 70
    "Not healed (failed safely)" : 9
```

</td>
<td width="50%" valign="top">

**Static fallback chain — 277 cases**

```mermaid
%%{init: {'theme':'base','themeVariables':{'pie1':'#2a6a46','pie2':'#9fcbb0','pie3':'#d99a1f','pie4':'#c2531a'}}}%%
pie showData
    title Fallback chain: 277 cases
    "Healed correctly" : 199
    "Correctly refused" : 28
    "Missed" : 8
    "FALSE HEAL — wrong element" : 42
```

</td>
</tr>
</table>

| Strategy | Heals where it should | False heals | Correct refusals | Mean time |
| :--- | ---: | ---: | ---: | ---: |
| No healing | 0.0% | 0% (0) | 100.0% | 0.0 s |
| Fallback chain (first unique fallback) | 96.1% | **17.4% (42)** | 40.0% | 2.7 s |
| **🟢 TestSphere healer** | **95.7%** | **0.0% (0)** | **100.0%** | 3.1 s |

> [!IMPORTANT]
> A heal counts as **correct** only if the healed locator resolves to the very element that was the target (checked on a marked copy of the page). The benchmark is a **CI gate** — any false heal fails the build. Full report: [`docs/healing-benchmark.md`](docs/healing-benchmark.md).

| Mutation | Should heal? | Cases | TestSphere |
| :--- | :---: | ---: | :--- |
| testid-renamed | ✅ | 21 | 21/21 healed |
| testid-removed | ✅ | 21 | 21/21 healed |
| id-renamed | ✅ | 21 | 21/21 healed |
| class-renamed | ✅ | 19 | 19/19 healed |
| wrapped / moved | ✅ | 42 | 42/42 healed |
| look-alike-added | ✅ | 21 | 21/21 healed |
| everything-renamed | ✅ | 21 | 12/21 healed (hard case) |
| **removed** | ⛔ | 21 | **21/21 refused** |
| **replaced-by-look-alike** | ⛔ | 21 | **21/21 refused** |
| **tag-changed** | ⛔ | 17 | **17/17 refused** |
| **input-type-changed** | ⛔ | 11 | **11/11 refused** |

---

## 🛡️ Security: the attacker agent

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#e4f1e8','primaryBorderColor':'#2a6a46','primaryTextColor':'#17402c','lineColor':'#2a6a46'}}}%%
flowchart LR
    T(["🎯 Target URL"]) --> S{"In allowlist?"}
    S -->|no| STOP(["⛔ Refused"])
    S -->|yes| P["🔍 Passive scan\none GET per page, no payloads\nheaders · cookies · CORS · TLS\nforms · information disclosure"]
    P --> O{"Active DAST on?\n+ domain ownership proven?"}
    O -->|no| TR
    O -->|yes| A["💣 Active probes\nreflected XSS · SQL injection\nopen redirect"]
    A --> BR["🌐 Each XSS runs in a real browser"]
    BR -->|executes| PRV["🔴 Proven finding"]
    BR -->|reflected only| UNC["🟡 Unconfirmed — not reported as proven"]
    PRV --> TR
    UNC --> TR
    TR["🧠 AI triage\nprioritize · real-world risk · draft fix\n(reasons only over in-scope findings)"] --> FIX["🛠️ Fix patch → PR / MR"]
    classDef good fill:#e4f1e8,stroke:#2a6a46,color:#17402c
    classDef bad fill:#fbe6da,stroke:#c2531a,color:#7a2e0e
    class P,TR,FIX good
    class STOP,A,PRV bad
```

| Mode | What it sends | Where it runs |
| --- | --- | --- |
| **Passive** (default) | One normal GET per page, no payloads | Any public site in the allowlist |
| **Active (DAST)** | Reflected-XSS, SQL-injection and open-redirect probes | Only apps you own, with a verified token at `/.well-known/testsphere-verify.txt` |

> [!NOTE]
> Active scans need proof of domain ownership: a project token published at `/.well-known/testsphere-verify.txt` via `POST /api/projects/{id}/domain-verification`, valid 30 days. See `REQUIRE_DOMAIN_VERIFICATION` in [`.env.example`](.env.example).

---

## 🤖 AI agents and the LLM fallback chain

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#e4f1e8','primaryBorderColor':'#2a6a46','primaryTextColor':'#17402c','lineColor':'#2a6a46','clusterBkg':'#fbfaf7','clusterBorder':'#d6cfc5'}}}%%
flowchart LR
    subgraph AG["Agents — backend/agents/"]
        direction TB
        PL["📝 Test Planner"]
        EX["🧭 AI Explorer"]
        FA["🔬 Failure Analyzer"]
        HE["🩹 AI Healer"]
        OR["🎛️ Orchestrator\nretry · heal · abort"]
    end
    AG ==>|every LLM call| CH
    subgraph CH["LLM fallback chain — largest context window first"]
        direction LR
        G1["Gemini"] -->|rate limit| G2["NVIDIA Nemotron"] -->|rate limit| G3["NVIDIA Gemma"] -->|rate limit| G4["Groq"]
    end
    CH -.->|"a provider that hit its limit is left out until it resets\nthe run continues on the next"| AG
    classDef a fill:#e4f1e8,stroke:#2a6a46,color:#17402c
    classDef m fill:#fbf0d4,stroke:#d99a1f,color:#5c4300
    class PL,EX,FA,HE,OR a
    class G1,G2,G3,G4 m
```

| Agent | Does | Code |
| --- | --- | --- |
| **Test Planner** | Plans tests from the page analysis, the written goal and the codebase; every element it uses must exist on the page | `agents/planner/` |
| **Test Studio** | Turns a plain-English instruction into steps, checked against the live page before anything runs | `app/services/test_studio.py` |
| **Flow suggestions** | Ranks the user flows most worth testing from routes and the live page | `app/services/flow_suggest.py` |
| **AI Explorer** | Reaches a written goal in a live browser once (opening menus, following tabs, never deleting or paying) and records it as a reusable test | `agents/explorer/` |
| **Failure Analyzer** | Classifies why a test failed and decides whether healing can help | `agents/analyzer/` |
| **AI Healer** | Proposes a replacement locator, accepted only if a re-run passes | `agents/healer/` |
| **Orchestrator** | Coordinates agents with a recovery policy (retry, heal, abort) | `agents/orchestration/` |

> [!NOTE]
> **A web page cannot steer an agent.** Text from the site reaches the AI only as fenced, untrusted data, and every action the AI proposes is checked in code (guardrails, selector whitelist, heal checks, scan scope). See [`agents/llm/untrusted.py`](backend/agents/llm/untrusted.py).

---

## 🏗️ Architecture

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#e4f1e8','primaryBorderColor':'#2a6a46','primaryTextColor':'#17402c','lineColor':'#2a6a46','clusterBkg':'#fbfaf7','clusterBorder':'#d6cfc5'}}}%%
flowchart TB
    subgraph PEOPLE["👥 People and tools"]
        UI["🖥️ Dashboard\nReact · frontend/"]
        GH["🐙 GitHub / GitLab\npush webhooks"]
        MCP["🤖 Coding agents\nMCP server"]
    end
    subgraph API["⚙️ API — FastAPI · backend/app/"]
        direction LR
        Studio["Test Studio"]
        Pipe["Pipeline runner\nscheduler · worker"]
        Heals["Heal review"]
        Sec["Security scans"]
        Rep["Reports · PDF · JUnit"]
    end
    subgraph AGENTS["🧠 AI agents — backend/agents/"]
        direction LR
        Planner["Planner"] ~~~ Explorer["Explorer"] ~~~ Analyzer["Analyzer"] ~~~ Healer["Healer"] ~~~ Orch["Orchestrator"]
    end
    LLM[["🔗 LLM fallback chain\nGemini → Nemotron → Gemma → Groq"]]
    Engine["🎭 Playwright engine\nChromium · Firefox · WebKit\nbackend/engine/"]
    Ingest["📦 Codebase ingestion\nbackend/ingestion/"]
    DB[("🗄️ Firestore or local JSON")]
    Art[("🖼️ Artifacts\ndisk · S3 · GCS")]
    Mem[("🧬 Healing memory")]
    Site(("🌐 Your web app"))

    UI --> API
    GH --> Pipe
    MCP --> API
    Pipe --> Ingest
    Pipe --> AGENTS
    Studio --> Planner
    AGENTS --> LLM
    Orch --> Engine
    Engine --> Site
    Sec --> Site
    Engine --> Art
    API --> DB
    Healer --> Mem

    classDef core fill:#e4f1e8,stroke:#2a6a46,color:#17402c
    classDef store fill:#fbf0d4,stroke:#d99a1f,color:#5c4300
    classDef ext fill:#e4ecfa,stroke:#2f62bd,color:#1d3f73
    class Engine,Ingest,Studio,Pipe,Heals,Sec,Rep,Planner,Explorer,Analyzer,Healer,Orch core
    class DB,Art,Mem store
    class UI,GH,MCP,Site,LLM ext
```

The repository has three parts: **`backend/`** (all Python — `pyproject.toml`, the dependency lock and tests live there, every Python command runs from it), **`frontend/`** (the dashboard) and **`docs/`**. Each has its own `Dockerfile`; [`docker-compose.yml`](docker-compose.yml), [`deploy/aws-ec2`](deploy/aws-ec2/README.md) and the Firestore rules stay at the root.

```
frontend/  React dashboard ──────────────▶ backend/app/   FastAPI
                                             │  api/           REST endpoints
                                             │  pipeline/      runner, scheduler, verified deploy
                                             │  orchestration/ ties agents to the engine
                                             │  database/      Store: Firestore, local JSON, memory
                                             │  artifacts.py   screenshots, DOM snapshots, traces
                                             │  github.py  notify.py  netguard.py  http_hardening.py
                                             ▼
        backend/agents/    planner, failure analyzer, healing, memory, LLM client
        backend/engine/    Playwright runner, locator healer, egress guard, benchmarks
        backend/security/  passive + active scanner, remediation, fix patcher
        backend/ingestion/ repository blueprint
```

| Folder | Contents |
| --- | --- |
| [`backend/app/`](backend/app/) | FastAPI API, automated pipeline and scheduler, pipeline worker, verified deploy, artifact store, integrations (GitHub, Slack), sign-in and data isolation, request hardening, MCP server |
| [`backend/agents/`](backend/agents/) | Test Planner, Failure Analyzer, healing decision engine, healing memory, agent orchestrator and recovery policy, provider-independent LLM client (mock, local, OpenAI-compatible API) |
| [`backend/engine/`](backend/engine/) | Playwright execution engine, locator healer, outbound request guard for the browser, healing benchmarks |
| [`backend/security/`](backend/security/) | Passive and active security scanner, remediation proposals, fix patch generator |
| [`backend/ingestion/`](backend/ingestion/) | Repository cloning and static analysis |
| [`backend/tests/`](backend/tests/) | Unit, integration, engine and end-to-end tests |
| [`backend/scripts/`](backend/scripts/) | Load test, test-generation evaluation |
| [`frontend/`](frontend/) | React dashboard with its design system, live pipeline loop, run pages, reports, security, profile and privacy pages |
| [`docs/`](docs/) | Architecture, operations, contributing guide and benchmark reports |

### Verified deploy with automatic rollback

```mermaid
%%{init: {'theme':'base','themeVariables':{'actorBkg':'#17402c','actorTextColor':'#ffffff','actorBorder':'#17402c','signalColor':'#2a6a46','noteBkgColor':'#fbf0d4','noteTextColor':'#5c4300','activationBkgColor':'#e4f1e8'}}}%%
sequenceDiagram
    autonumber
    participant TS as TestSphere
    participant Host as Render · Vercel · Netlify · Actions
    participant App as New version
    TS->>Host: Call deploy hook
    Host-->>App: Build and start
    loop until healthy or timeout
        TS->>App: Health check
    end
    alt healthy
        TS->>App: Run smoke tests
        alt smoke pass
            App-->>TS: ✅ Verified
        else smoke fail
            TS->>Host: ↩️ Rollback hook
        end
    else never healthy
        TS->>Host: ↩️ Rollback hook
    end
    Note over TS,Host: A failed rollout never stays live.
```

---

## 📈 Measured results

Every number is generated by a script in this repository, and the two benchmarks gate CI.

| Measurement | Result |
| --- | --- |
| **Self-healing benchmark** — 277 broken-locator cases (4 pages × every target × 15 mutations), [details](docs/healing-benchmark.md) | Heals **95.7%** of the cases where healing is right with **0 false heals**, and refuses **100%** of the cases where it is wrong. A static fallback chain heals 96.1% but **17.4%** of its heals hit the wrong element. |
| **Plain-English tests** (Test Studio) — 15 instructions, 19 real bugs, [details](docs/studio-eval.md) | **18 of 19** bugs caught with **0 false alarms** (rule-based planner, no AI model); 6 of 7 on held-out instructions it was never tuned on |
| **Live sites** — the-internet.herokuapp.com, saucedemo.com, practicetestautomation.com, TodoMVC | 4 of 4 run the written goal (log in, add an item) and pass |
| **Real repositories** — FastAPI, Express and Django RealWorld apps, microblog, Flask | 5 of 5 get a fix patch that applies to a fresh clone and compiles |
| **Security and robustness** — SSRF, access control, input limits, webhook signatures, rate limits | 52 of 52 checks pass |
| **Load** — one API worker, [details](docs/load-test.md) | ~600–700 requests/s from 1 to 100 concurrent clients (p95 250 ms, no errors); 8 pipeline runs at once finish in 27 s at ~460 MB |
| **Accessibility** | WCAG 2.1 AA (axe) on every dashboard page, light and dark |
| **Automated tests** | 2,000+ backend, engine and end-to-end tests and 95 frontend unit tests, in CI; both benchmarks gate every change |

### ⚡ Load test: throughput stays flat, zero errors

<div align="center">
<img src="docs/assets/load-test.svg" alt="Load test: requests/s and p95 latency from 1 to 100 concurrent clients" width="100%"/>
</div>

<br/>

<table>
<tr>
<td width="50%" valign="top">

**Pipeline runs started together**

```mermaid
%%{init: {'theme':'base','themeVariables':{'xyChart':{'plotColorPalette':'#2a6a46','titleColor':'#17402c','backgroundColor':'#fbfaf7','plotColorPalette':'#2a6a46,#d99a1f'}}}}%%
xychart-beta
    title "Time to finish all runs (seconds)"
    x-axis "Runs at once" [1, 2, 4, 8]
    y-axis "Seconds" 0 --> 30
    bar [3, 7, 13, 27]
```

</td>
<td width="50%" valign="top">

**Peak memory — server + all Chromium instances**

```mermaid
%%{init: {'theme':'base','themeVariables':{'xyChart':{'plotColorPalette':'#d99a1f','titleColor':'#17402c','backgroundColor':'#fbfaf7'}}}}%%
xychart-beta
    title "Peak memory (MB) — plateaus near 460 MB"
    x-axis "Runs at once" [1, 2, 4, 8]
    y-axis "MB" 0 --> 500
    bar [222, 462, 457, 462]
```

</td>
</tr>
</table>

> [!TIP]
> `ENGINE_MAX_BROWSERS` caps how many browsers run at once; further runs queue instead of exhausting memory. Use at least 1 GB with `ENGINE_MAX_BROWSERS=1`, or 2 GB with the default of 2. For heavy parallel workloads, use `PIPELINE_EXECUTION=worker`.

### 🐞 Test Studio: real bugs caught from plain English

```mermaid
%%{init: {'theme':'base','themeVariables':{'pie1':'#2a6a46','pie2':'#c2531a'}}}%%
pie showData
    title 19 real bugs · rule-based planner (no AI model)
    "Caught (18)" : 18
    "Missed (1)" : 1
```

15 of 15 instructions became a saveable test, 15 of 15 pass on the healthy site, **0 false alarms**. The one miss is in the instruction itself (the check text also appears on the wrong page). Full report: [`docs/studio-eval.md`](docs/studio-eval.md).

---

## 🚀 Getting started

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#e4f1e8','primaryBorderColor':'#2a6a46','primaryTextColor':'#17402c','lineColor':'#2a6a46'}}}%%
flowchart LR
    A["1 · Clone"] --> B["2 · Install backend\n+ Chromium"] --> C["3 · Install dashboard"] --> D["4 · cp .env.example .env\nworks offline by default"] --> E["5 · Run API :8000"] --> F["6 · Run dashboard :3000"] --> G(["🎉 Run your first pipeline"])
    classDef n fill:#e4f1e8,stroke:#2a6a46,color:#17402c
    class A,B,C,D,E,F,G n
```

```bash
git clone https://github.com/Krishna201i/TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform.git
cd TestSphere-AI-Autonomous-Agentic-QA-Self-Healing-Testing-Platform

# Python package with development tools, and the browser (all Python lives in backend/)
cd backend
pip install -r requirements.txt && pip install -e ".[dev]"
python -m playwright install chromium
cd ..

# Dashboard
cd frontend && npm install && cd ..

# Settings: works fully offline by default
# (LLM_PROVIDER=mock, local JSON database, sign-in off)
cp .env.example .env
```

**Run the platform:**

```bash
# Terminal 1 — API
cd backend && python -m uvicorn app.main:app --port 8000

# Terminal 2 — Dashboard
cd frontend && npm run dev
# → open http://localhost:3000
```

**Or in Docker** (dashboard on nginx, backend with Chromium):

```bash
docker compose up --build   # → http://localhost:8080
```

<details>
<summary><b>🧪 Run tests, benchmarks and the security scanner</b></summary>
<br/>

```bash
# Backend tests (app, agents, engine, e2e)
cd backend && python -m pytest -q

# Frontend unit tests and design-token lint
cd frontend && npm test

# Self-healing benchmark (--quick for a fast subset; drop it for all 277 cases)
cd backend && python -m engine.heal_benchmark --quick

# Load test
cd backend && python scripts/loadtest.py

# Passive security scan (loopback is always in scope)
cd backend && python -m security http://127.0.0.1:8000/

# Active (DAST) scan — only on apps you own
cd backend && python -m security http://127.0.0.1:8000/?q=x --active
```

</details>

> [!TIP]
> New here? The [10-minute demo script](docs/demo-script.md) walks through autonomous runs, Test Studio, QA reports and a live self-heal on a site you can break on purpose.

---

## ⚙️ Configuration and deployment

Production runs on one AWS EC2 instance (API + dashboard, a pipeline worker and Caddy for HTTPS; see [`deploy/aws-ec2`](deploy/aws-ec2/README.md)) with Firebase (Authentication and Firestore).

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#e4f1e8','primaryBorderColor':'#2a6a46','primaryTextColor':'#17402c','lineColor':'#2a6a46','clusterBkg':'#fbfaf7','clusterBorder':'#d6cfc5'}}}%%
flowchart LR
    Dev["👩‍💻 git push"] --> CI["🧪 GitHub Actions CI\ntests · benchmarks · security scan"]
    CI -->|main passes| CD["🚀 Deploy workflow\npull-based CD"]
    CD --> EC2
    subgraph EC2["☁️ AWS EC2"]
        direction TB
        Caddy["🔒 Caddy — HTTPS"] --> App["API + dashboard\nFastAPI · React build"]
        Worker["⚙️ Pipeline worker\nPIPELINE_EXECUTION=worker"]
    end
    App <--> FB[("🔥 Firebase\nAuth · Firestore")]
    Worker <--> FB
    App --> S3[("🪣 S3 / GCS\nartifacts")]
    Worker --> S3
    CD -.->|health check fails| RB(["↩️ Automatic rollback"])
    User["👤 Browser"] --> Caddy
    classDef n fill:#e4f1e8,stroke:#2a6a46,color:#17402c
    classDef s fill:#fbf0d4,stroke:#d99a1f,color:#5c4300
    class CI,CD,Caddy,App,Worker n
    class FB,S3 s
```

**Key environment variables:**

| Variable | Purpose |
| --- | --- |
| `FIREBASE_CREDENTIALS`, `FIREBASE_WEB_API_KEY`, `FIREBASE_AUTH_DOMAIN` | Database and sign-in |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | AI model (`mock` · `local` Ollama · any OpenAI-compatible `api`) |
| `LLM_PROVIDER=chain`, `NVIDIA_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY` | Fallback chain: Gemma → Nemotron → Groq → Gemini; `python -m agents.llm.check` tests every provider |
| `SECURITY_SCAN_ALLOWED_HOSTS` | Hosts the scanner may contact |
| `SECURITY_ACTIVE_SCAN` | Enable DAST probes (off by default) |
| `REQUIRE_DOMAIN_VERIFICATION` | Domain ownership check for active scans (`auto` / `on` / `off`) |
| `ARTIFACT_STORE=s3` (or `gcs`), `ARTIFACT_BUCKET` | Store screenshots and traces in S3 or GCS |
| `TOKEN_ENCRYPTION_KEY` | Encrypts connected GitHub tokens (required when hosted) |
| `PIPELINE_EXECUTION=worker` | Move pipeline runs to a separate worker service |
| `DASHBOARD_URL` | Base URL for Slack alerts and GitHub commit statuses |

Full reference — every setting, the two Docker images, the worker, Firestore rules and indexes, and CI — in the [Deployment & Operations Guide](docs/deployment-operations.md).

---

## 🧰 Tech stack

<div align="center">

![Python](https://img.shields.io/badge/Python-17402c?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-2a6a46?style=flat-square&logo=fastapi&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-17402c?style=flat-square&logo=playwright&logoColor=white)
![React](https://img.shields.io/badge/React-2a6a46?style=flat-square&logo=react&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-17402c?style=flat-square&logo=vite&logoColor=white)
![Firebase](https://img.shields.io/badge/Firebase-2a6a46?style=flat-square&logo=firebase&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-17402c?style=flat-square&logo=docker&logoColor=white)
![nginx](https://img.shields.io/badge/nginx-2a6a46?style=flat-square&logo=nginx&logoColor=white)
![Caddy](https://img.shields.io/badge/Caddy-17402c?style=flat-square&logo=caddy&logoColor=white)
![AWS EC2](https://img.shields.io/badge/AWS%20EC2-2a6a46?style=flat-square&logo=amazonaws&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-17402c?style=flat-square&logo=githubactions&logoColor=white)
![Gemini](https://img.shields.io/badge/Gemini-2a6a46?style=flat-square&logo=googlegemini&logoColor=white)
![NVIDIA](https://img.shields.io/badge/NVIDIA-17402c?style=flat-square&logo=nvidia&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-2a6a46?style=flat-square)
![pytest](https://img.shields.io/badge/pytest-17402c?style=flat-square&logo=pytest&logoColor=white)
![Vitest](https://img.shields.io/badge/Vitest-2a6a46?style=flat-square&logo=vitest&logoColor=white)

</div>

---

## 📚 Documentation

| Read | Contents |
| --- | --- |
| [🧭 Platform overview](docs/platform-overview.md) | The five pillars, full architecture diagram, measured results |
| [🎬 Demo script](docs/demo-script.md) | A 10-minute walkthrough — autonomous run, Test Studio, QA, self-heal, platform |
| [🏛️ Backend architecture & API](docs/backend-architecture.md) | Services, endpoints, data model |
| [🎭 Browser execution engine](docs/engine-architecture.md) | Playwright runner, artifacts, egress guard |
| [🩹 Self-healing & orchestration](docs/self-healing-orchestration.md) | Healing decisions, healing memory, recovery policy |
| [🔌 Integration guide](docs/integration-guide.md) | GitHub, GitLab, Bitbucket, Slack, webhooks |
| [🤝 MCP server](docs/mcp-server.md) | Let your coding agent query and drive TestSphere |
| [🚢 Deployment & operations](docs/deployment-operations.md) | Every setting, Docker images, worker, Firestore, CI |
| [📏 Healing benchmark](docs/healing-benchmark.md) | 277 cases, methodology, per-mutation breakdown |
| [📏 Test Studio benchmark](docs/studio-eval.md) | 15 instructions, 19 bugs, held-out evaluation |
| [📏 Load test](docs/load-test.md) | Throughput, latency, concurrent runs, sizing guide |
| [🤲 Contributing](docs/CONTRIBUTING.md) | How to work on the project, branch layout, CI |

---

## 🔐 Security and privacy

- 🧱 **Scope-limited scanning.** The scanner only contacts hosts in an explicit allowlist; testing a site needs its owner's permission. Passive by default; active (DAST) probes are opt-in behind a server switch and require domain-ownership proof.
- 🌐 **SSRF guard on every request.** Every outbound request — including everything the test browser loads — goes through a guard that resolves each host once, refuses internal addresses and connects only to the address it resolved (no DNS rebinding).
- 🧪 **Prompt-injection safe.** Text from the site under test reaches the AI only as fenced, untrusted data, and every action the AI proposes is checked in code (guardrails, selector whitelist, engine heal checks, scan scope), so a page that tries to instruct the AI cannot make a run click, type or navigate somewhere harmful.
- 👤 **Your data stays yours.** Each user sees only their own data. The privacy notice in the dashboard explains what is stored, and *Delete account* erases it together with the sign-in account.

---

## 👥 Team

<table>
<tr>
<td align="center" width="33%" valign="top">

### Vinamra Bhatnagar

**Member 1 — AI agents & intelligence**

`agents/`

[![vinamra-branch](https://img.shields.io/badge/branch-vinamra--branch-2a6a46?style=flat-square&logo=git&logoColor=white)](../../tree/vinamra-branch)

</td>
<td align="center" width="33%" valign="top">

### Krishna Singh

**Member 2 — Browser engine, self-healing & security testing**

`engine/` · `security/` · `ingestion/` · `scripts/`

[![krishna-branch](https://img.shields.io/badge/branch-krishna--branch-2a6a46?style=flat-square&logo=git&logoColor=white)](../../tree/krishna-branch)

</td>
<td align="center" width="33%" valign="top">

### Prashansha Maheshwari

**Member 3 — Platform backend, pipeline & dashboard**

`backend/` · `frontend/` · `docs/`

[![prashansha-branch](https://img.shields.io/badge/branch-prashansha--branch-2a6a46?style=flat-square&logo=git&logoColor=white)](../../tree/prashansha-branch)

</td>
</tr>
</table>

Each member branch contains the full project; its README describes that member's part in detail. Work is merged into `main` through pull requests that pass CI.

<details>
<summary><b>🏅 Contributions in detail</b></summary>
<br/>

| Member | Contributed |
| --- | --- |
| **Vinamra Bhatnagar** | Founded the AI agent layer: the shared agent schemas and contracts, the provider-independent LLM client (mock provider, response parser, `LLMClientSession` with validation and retry), the Test Planner Agent (schemas, prompt architecture, mock scenarios, generation pipeline), the failure classifier and Failure Analysis Agent, the self-healing contracts, test prioritization, their tests. |
| **Krishna Singh** | The Playwright engine and locator healing with its benchmark, the passive and active security scanner and AI triage, codebase ingestion, fix patches and pull requests, verified deploy, the real LLM providers, persistent healing memory, the AI explorer, failure reports and PDF export, Firestore storage, CI and security scanning, hosting, and most of the current backend and dashboard. |
| **Prashansha Maheshwari** | The first backend platform and workflow orchestration, the plan-and-execute API with live SSE events, the first React dashboard and its connection to the backend, the Vercel and Render deployment setup, the two-container Docker setup (frontend on nginx, backend) with its CI smoke tests and continuous deployment to AWS, and the architecture, API, engine, integration and operations documentation, plus [`CONTRIBUTING.md`](docs/CONTRIBUTING.md). |

</details>

---

## 📄 License

Released under the [MIT License](LICENSE).

<div align="center">
<br/>

**If TestSphere AI saves you a flaky-test afternoon, give it a ⭐**

<br/>
<sub>Built with care by Vinamra, Krishna and Prashansha.</sub>

</div>
