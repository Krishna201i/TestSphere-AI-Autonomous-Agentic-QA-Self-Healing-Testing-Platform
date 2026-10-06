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
                                       | Playwright re-runs with new  |
                                       | healed selector              |
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

---

## 2. Multi-Agent Healing Subsystems

The self-healing architecture comprises five cooperating specialized agents and engines located in [`agents/`](file:///agents/):

### 2.1 Failure Analysis Agent (`agents/analyzer/analyzer.py`)
- Ingests the `FailureContext`, failure message, screenshot, and full serialized DOM snapshot.
- Differentiates between actual software bugs (e.g. 500 error on submit, unhandled exception in app) versus test automation flakiness / locator degradation.
- Determines whether self-healing is eligible for this failure type.

### 2.2 Candidate Selector Generator (`agents/healer/candidate_generator.py`)
- Analyzes DOM element attributes in the vicinity of the failed target.
- Generates a candidate pool of alternative locators spanning:
  - Accessible name and ARIA role (`getByRole('button', { name: 'Submit' })`)
  - Semantic test attributes (`data-testid`, `data-qa`, `data-cy`)
  - Visible text content (`text="Log In"`)
  - Robust hierarchical CSS paths excluding fragile auto-generated hash classes

### 2.3 Candidate Scorer (`agents/healer/candidate_scorer.py`)
- Scores each generated candidate on a normalized 0.0 to 1.0 confidence scale.
- Factors evaluated:
  - **Uniqueness**: Does the selector match exactly 1 DOM node?
  - **Stability**: Does the selector rely on semantic attributes rather than volatile class names?
  - **Simplicity**: Shorter, cleaner selectors receive higher confidence weight.

### 2.4 Healing Decision Engine (`agents/healer/healing_decision.py`)
- Applies the `RecoveryPolicy` rules (max retry limit, confidence threshold cutoff).
- Selects the optimal candidate or marks the step unhealable if confidence falls below threshold.

### 2.5 Feedback & Learning Processor (`agents/healer/healing_feedback.py`)
- Records the outcome of the self-healing attempt.
- Feeds positive reinforcement back to the memory store (`HealingHistoryMemory`) so future test executions can directly utilize the healed locator without repeating the failure.

---

## 3. Schema Bridging Layer (`backend/orchestration/converters.py`)

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
