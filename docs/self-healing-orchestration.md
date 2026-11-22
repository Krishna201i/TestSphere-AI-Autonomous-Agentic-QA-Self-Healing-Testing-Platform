# TestSphere-AI Self-Healing & Autonomous Orchestration

## 1. The Autonomous QA Lifecycle

The core innovation of TestSphere-AI is its closed-loop self-healing automation lifecycle. When user interface changes (such as ID renames, dynamic CSS hash changes, structural DOM restructurings, or updated button labels) break traditional automated tests, TestSphere-AI detects the failure, diagnoses root cause, synthesizes alternative selectors using LLM intelligence, executes the healed step, verifies success, and persists the healed locator into the test definition.

```
       +--------------------------------------------------------------+
       |                  1. Test Plan Generation                     |
       |  LLMTestPlanner synthesizes TestSteps from App Context       |
       +------------------------------+-------------------------------+
                                      |
                                      v
       +--------------------------------------------------------------+
       |                  2. Schema Transformation                    |
       |  converters.py bridges Member 1 Plan -> Member 2 Engine Spec |
       +------------------------------+-------------------------------+
                                      |
                                      v
       +--------------------------------------------------------------+
       |                  3. Browser Execution                        |
       |  PlaywrightRunner executes steps in isolated BrowserContext  |
       +------------------------------+-------------------------------+
                                      |
                       +--------------+--------------+
                       |                             |
                    [Passed]                      [Failed]
                       |                             |
                       v                             v
           +-----------------------+   +------------------------------+
           | Record PASSED Status  |   |   4. Failure Classification  |
           | Continue next step    |   | Capture DOM Snapshot & Image |
           +-----------------------+   +--------------+---------------+
                                                      |
                                                      v
                                       +------------------------------+
                                       |  5. Root Cause Analysis      |
                                       | FailureAnalyzerAgent detects |
                                       | LOCATOR_CHANGED / TIMEOUT    |
                                       +--------------+---------------+
                                                      |
                                                      v
                                       +------------------------------+
                                       |  6. Candidate Generation     |
                                       | CandidateGenerator inspects  |
                                       | DOM & generates alternatives |
                                       +--------------+---------------+
                                                      |
                                                      v
                                       +------------------------------+
                                       |  7. Scoring & Decision       |
                                       | CandidateScorer scores fits  |
                                       | HealingDecisionEngine picks  |
                                       +--------------+---------------+
                                                      |
                                                      v
                                       +------------------------------+
                                       |  8. Re-execution & Verify    |
                                       | The candidate is OFFERED to  |
                                       | the engine as a fallback;    |
                                       | the engine's own checks      |
                                       | decide (see 1.1)             |
                                       +--------------+---------------+
                                                      |
                                       +--------------+--------------+
                                       |                             |
                                   [Success]                     [Exhausted]
                                       |                             |
                                       v                             v
                        +-----------------------+     +-----------------------+
                        | 9. Record HEALED Run  |     | Record FAILED Run     |
                        | Update TestCase Model |     | Report Error to User  |
                        +-----------------------+     +-----------------------+
```


### 1.1 Who decides a heal

The AI layer (steps 6–7) only **proposes** a replacement. The re-run in step 8 keeps the
broken locator and offers the candidate as the step's first fallback, so the engine judges it
in the live page exactly as it judges its own fallbacks: same tag and kind of control, a shared
identifying feature (id, accessible name, text, href), and a score of at least 0.75 against the
stored fingerprint. A heal counts only when the engine accepted that candidate **and** the whole
test then passed. A candidate the engine refuses (a look-alike after the real element was
removed) leaves the run FAILED; it is never recorded as a validated heal.

Two more rules keep a failure from turning into a pass:

- A check is not a locator to heal: `assert_visible` on an element that is on the page but
  hidden fails as a check; only a locator that matches nothing goes to healing.
- Healing memory is partitioned by owner: one account's history is never the baseline for
  another account's heal.

**Writing a heal back.** When a run passes after a heal the engine made with confidence of at
least 0.90, the stored test is updated: its steps target the new locator, the old one becomes the
first fallback (a UI change that is undone heals straight back), and the change is listed in the
test case's `locator_history`. The next run passes as written instead of healing again. A less
certain heal is not written back: it keeps healing from the learned fallback and the run says
HEALED, so a person sees it. Tests the pipeline rebuilds from the live page on every run are not
rewritten (explorer recordings are).

CI runs the quick healing benchmark with `--gate 0.90`: any false heal or missed refusal fails
the build. `backend/tests/app/test_no_false_heals.py` covers the AI layer end to end in a real
browser.

---

## 2. Multi-Agent Healing Subsystems

The self-healing architecture comprises five cooperating specialized agents and engines located in [`agents/`](file:///agents/):

### 2.1 Failure Analysis Agent (`backend/agents/analyzer/analyzer.py`)
- Ingests the `FailureContext`, failure message, screenshot, and full serialized DOM snapshot.
- Differentiates between actual software bugs (e.g. 500 error on submit, unhandled exception in app) versus test automation flakiness / locator degradation.
- Determines whether self-healing is eligible for this failure type.

### 2.2 Candidate Selector Generator (`backend/agents/healer/candidate_generator.py`)
- Analyzes DOM element attributes in the vicinity of the failed target.
- Generates a candidate pool of alternative locators spanning:
  - Accessible name and ARIA role (`getByRole('button', { name: 'Submit' })`)
  - Semantic test attributes (`data-testid`, `data-qa`, `data-cy`)
  - Visible text content (`text="Log In"`)
  - Robust hierarchical CSS paths excluding fragile auto-generated hash classes

### 2.3 Candidate Scorer (`backend/agents/healer/candidate_scorer.py`)
- Scores each generated candidate on a normalized 0.0 to 1.0 confidence scale.
- Factors evaluated:
  - **Uniqueness**: Does the selector match exactly 1 DOM node?
  - **Stability**: Does the selector rely on semantic attributes rather than volatile class names?
  - **Simplicity**: Shorter, cleaner selectors receive higher confidence weight.

### 2.4 Healing Decision Engine (`backend/agents/healer/healing_decision.py`)
- Applies the `RecoveryPolicy` rules (max retry limit, confidence threshold cutoff).
- Selects the optimal candidate or marks the step unhealable if confidence falls below threshold.

### 2.5 Feedback & Learning Processor (`backend/agents/healer/healing_feedback.py`)
- Records the outcome of the self-healing attempt.
- Feeds positive reinforcement back to the memory store (`HealingHistoryMemory`) so future test executions can directly utilize the healed locator without repeating the failure.

---

## 3. Schema Bridging Layer (`backend/app/orchestration/converters.py`)

Because Member 1 (AI Agent Layer) and Member 2 (Browser Engine) were developed with decoupled, domain-specific schemas, the converter layer serves as the zero-loss bridge:

| Member 1 Schema (`agents.planner.schemas`) | Converter Function | Member 2 Engine Schema (`engine.schemas`) |
| :--- | :--- | :--- |
| `Member1TestStep(action, target, ...)` | `convert_step_to_engine()` | `engine.schemas.Target`, `StepAction` |
| `Member1TestCase(name, steps, ...)` | `convert_case_to_engine()` | Sequence of executable engine steps |
| `engine.schemas.TestResult` | `convert_engine_result_to_member1()` | Agent execution telemetry format |

---

## 4. Real-Time Event Streaming (Server-Sent Events)

During test execution, `PlatformWorkflowOrchestrator` streams fine-grained events via SSE to the connected dashboard:

- **`step_start`**: Fired when browser begins executing a step.
- **`step_complete`**: Fired when step succeeds with duration and screenshot URL.
- **`step_failed`**: Fired when step fails, signaling start of healing analysis.
- **`healing_started`**: Fired with failure diagnostics and candidate generation count.
- **`healing_resolved`**: Fired when healed selector succeeds on browser re-try.
- **`run_finished`**: Final execution summary containing total pass/fail/heal metrics.
