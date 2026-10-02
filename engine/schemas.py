"""
engine/schemas.py
=================
All Pydantic v2 data models for the TestSphere-AI QA Execution Engine.

Public contract consumed by Member 1 (agent/LLM layer) and Member 3 (backend/dashboard).
JSON Schemas are exported separately via `export_schemas()` or the CLI helper
`python -m engine.schemas`.

Hierarchy
---------
Input side:
    EngineConfig  – global tunables (heal threshold, timeouts, headless…)
    RunOptions    – per-run overrides (subset of EngineConfig)
    TestPlan      – one test: metadata + ordered list of Steps
    Step          – one browser action
    Target        – element address (primary locator + fallbacks + fingerprint)
    ElementFingerprint – DOM snapshot of a successfully located element

Output side:
    TestResult    – top-level result for a full TestPlan run
    StepResult    – per-step outcome
    HealingReport – details of a locator-healing attempt
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ActionType(str, Enum):
    """All browser actions a Step can perform."""

    GOTO = "goto"
    CLICK = "click"
    FILL = "fill"
    PRESS = "press"
    SELECT = "select"
    ASSERT_TEXT = "assert_text"
    ASSERT_VISIBLE = "assert_visible"
    WAIT_FOR = "wait_for"


class StepStatus(str, Enum):
    """Outcome of a single step execution."""

    PASSED = "passed"
    FAILED = "failed"
    HEALED = "healed"


class TestStatus(str, Enum):
    """Aggregate outcome of a full test run."""

    PASSED = "passed"
    FAILED = "failed"
    HEALED = "healed"


# ---------------------------------------------------------------------------
# Element identity
# ---------------------------------------------------------------------------


class BoundingBox(BaseModel):
    """Pixel coordinates and dimensions of an element in the viewport."""

    model_config = ConfigDict(frozen=True)

    x: float = Field(..., description="Left edge, pixels from viewport origin")
    y: float = Field(..., description="Top edge, pixels from viewport origin")
    width: float = Field(..., ge=0)
    height: float = Field(..., ge=0)


class ElementFingerprint(BaseModel):
    """
    Rich DOM snapshot captured when an element is successfully located.

    Used by the healer to score live-DOM candidates against a previously
    known element, even after the original locator breaks.
    """

    model_config = ConfigDict(frozen=True)

    tag: str | None = Field(None, description="HTML tag name, lower-cased (e.g. 'button')")
    id: str | None = Field(None, description="Element id attribute")
    classes: list[str] = Field(default_factory=list, description="CSS class list")
    text: str | None = Field(None, description="Visible inner text, stripped")
    role: str | None = Field(None, description="ARIA role attribute or implicit role")
    aria_label: str | None = Field(None, description="aria-label attribute value")
    name: str | None = Field(None, description="name attribute (inputs, forms, etc.)")
    placeholder: str | None = Field(None, description="placeholder attribute")
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Any other relevant HTML attributes (data-*, type, href, ...)",
    )
    parent_chain: list[str] = Field(
        default_factory=list,
        description="Ordered list of ancestor tag#id.class strings, nearest first",
    )
    sibling_index: int | None = Field(
        None,
        description="0-based index among same-tag siblings within the parent",
    )
    bounding_box: BoundingBox | None = Field(
        None,
        description="Viewport bounding box at time of capture",
    )


class Target(BaseModel):
    """
    Fully-described element address.

    Member 1 can populate `primary_locator` and `fallback_locators` from
    their planner; Member 2 (engine) enriches `fingerprint` after a
    successful locate.
    """

    description: str = Field(
        ..., description="Human-readable description of the element (for logs/reports)"
    )
    primary_locator: str = Field(
        ..., description="First locator to try (CSS selector, XPath, role string, ...)"
    )
    fallback_locators: list[str] = Field(
        default_factory=list,
        description="Ordered fallback locators in priority order (most stable first)",
    )
    fingerprint: ElementFingerprint | None = Field(
        None,
        description=(
            "DOM fingerprint captured on last successful interaction; "
            "used by healer when all locators fail"
        ),
    )


# ---------------------------------------------------------------------------
# Test plan (input)
# ---------------------------------------------------------------------------


class Step(BaseModel):
    """One atomic browser action in a TestPlan."""

    step_id: str = Field(..., description="Stable, unique identifier within the plan")
    action: ActionType = Field(..., description="Browser action to perform")
    target: Target | None = Field(
        None,
        description="Element to act on; None for actions that don't require one (e.g. wait_for)",
    )
    value: str | None = Field(
        None,
        description="Input value for fill/press/select/goto (URL for goto)",
    )
    expected: str | None = Field(
        None,
        description="Expected value for assert_* actions",
    )
    timeout_ms: int = Field(
        5_000,
        ge=0,
        description="Per-step timeout in milliseconds",
    )


class TestPlan(BaseModel):
    """Complete specification for a single test run."""

    test_id: str = Field(..., description="Globally unique test identifier")
    name: str = Field(..., description="Human-readable test name")
    base_url: str = Field(
        ...,
        description="Root URL navigated to at test start (may be overridden per step)",
    )
    steps: list[Step] = Field(..., min_length=1, description="Ordered list of steps to execute")


# ---------------------------------------------------------------------------
# Run configuration
# ---------------------------------------------------------------------------


class EngineConfig(BaseModel):
    """
    Global engine configuration.

    Set once at engine start; individual runs may override a subset via
    RunOptions.
    """

    heal_threshold: float = Field(
        0.75,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score (0-1) for automatic locator acceptance",
    )
    default_timeout_ms: int = Field(
        5_000,
        ge=0,
        description="Default per-step timeout when Step.timeout_ms is not set",
    )
    headless: bool = Field(True, description="Run Chromium in headless mode")
    artifacts_dir: str = Field(
        "artifacts",
        description="Root directory for screenshots, DOM snapshots, and traces",
    )
    slow_mo_ms: int = Field(
        0,
        ge=0,
        description="Playwright slowMo delay in milliseconds (useful for debugging)",
    )
    tracing_enabled: bool = Field(
        False,
        description="Capture Playwright traces (.zip) per test; increases disk usage",
    )
    max_candidates: int = Field(
        20,
        ge=1,
        description="Maximum live-DOM candidates to evaluate during healing",
    )


class RunOptions(BaseModel):
    """
    Per-run overrides for EngineConfig fields.

    All fields are optional; only supplied fields override the engine default.
    """

    heal_threshold: float | None = Field(None, ge=0.0, le=1.0)
    default_timeout_ms: int | None = Field(None, ge=0)
    headless: bool | None = None
    artifacts_dir: str | None = None
    slow_mo_ms: int | None = Field(None, ge=0)
    tracing_enabled: bool | None = None
    max_candidates: int | None = Field(None, ge=1)

    def merged(self, base: EngineConfig) -> EngineConfig:
        """Return a new EngineConfig with non-None overrides applied."""
        overrides = {k: v for k, v in self.model_dump().items() if v is not None}
        return base.model_copy(update=overrides)


# ---------------------------------------------------------------------------
# Test results (output)
# ---------------------------------------------------------------------------


class HealingSignals(BaseModel):
    """Per-signal similarity scores contributing to overall candidate score."""

    attribute: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Score from id/class/attribute comparison",
    )
    text: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Score from visible text comparison (rapidfuzz)",
    )
    position: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Score from bounding-box proximity",
    )
    structure: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Score from DOM structural comparison (parent chain, sibling index)",
    )


class HealingCandidate(BaseModel):
    """One live-DOM candidate evaluated during a healing attempt."""

    locator: str = Field(..., description="CSS/XPath locator for this candidate")
    score: float = Field(..., ge=0.0, le=1.0, description="Weighted composite score")
    signals: HealingSignals = Field(..., description="Per-signal breakdown")


class HealingReport(BaseModel):
    """
    Full record of a locator-healing attempt.

    Returned even when healing fails (all scores below threshold), so that
    Member 1's agent can make a decision and Member 3 can display it.
    """

    original_locator: str = Field(..., description="The locator that failed")
    candidates: list[HealingCandidate] = Field(
        default_factory=list,
        description="All evaluated candidates, sorted best-first",
    )
    selected_locator: str | None = Field(
        None,
        description=(
            "Locator accepted automatically "
            "(None = healing failed / deferred to agent)"
        ),
    )
    confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Score of the selected locator (0 if none selected)",
    )
    strategy_used: str = Field(
        "",
        description=(
            "Short description of healing strategy "
            "(e.g. 'fallback[1]', 'fingerprint')"
        ),
    )


class StepResult(BaseModel):
    """Outcome of executing a single Step."""

    step_id: str
    status: StepStatus
    error: str | None = Field(None, description="Error message if status is failed")
    duration_ms: int = Field(..., ge=0)
    locator_used: str | None = Field(
        None,
        description="The locator that ultimately succeeded (or None for non-element actions)",
    )
    healing: HealingReport | None = Field(
        None,
        description="Present whenever a healing attempt was made (success or failure)",
    )
    screenshot_path: str | None = Field(
        None,
        description="Absolute path to PNG screenshot (captured on failure or always, per config)",
    )
    dom_snapshot_path: str | None = Field(
        None,
        description="Absolute path to saved HTML DOM snapshot",
    )
    console_logs: list[str] = Field(
        default_factory=list,
        description="Browser console messages collected during this step",
    )
    network_errors: list[str] = Field(
        default_factory=list,
        description="Failed network requests observed during this step",
    )


class TestResult(BaseModel):
    """Top-level result for a complete TestPlan execution."""

    test_id: str
    status: TestStatus
    started_at: datetime = Field(..., description="UTC timestamp when execution began")
    duration_ms: int = Field(..., ge=0, description="Total wall-clock time in milliseconds")
    steps: list[StepResult]
    artifacts_dir: str = Field(
        ...,
        description="Root directory where all artifacts for this run were written",
    )

    @property
    def passed_count(self) -> int:
        """Number of steps with status PASSED."""
        return sum(1 for s in self.steps if s.status == StepStatus.PASSED)

    @property
    def failed_count(self) -> int:
        """Number of steps with status FAILED."""
        return sum(1 for s in self.steps if s.status == StepStatus.FAILED)

    @property
    def healed_count(self) -> int:
        """Number of steps with status HEALED."""
        return sum(1 for s in self.steps if s.status == StepStatus.HEALED)


# ---------------------------------------------------------------------------
# JSON Schema export
# ---------------------------------------------------------------------------

# Models that Members 1 and 3 need to consume
_EXPORTED_MODELS: dict[str, type[BaseModel]] = {
    "EngineConfig": EngineConfig,
    "RunOptions": RunOptions,
    "TestPlan": TestPlan,
    "Step": Step,
    "Target": Target,
    "ElementFingerprint": ElementFingerprint,
    "BoundingBox": BoundingBox,
    "TestResult": TestResult,
    "StepResult": StepResult,
    "HealingReport": HealingReport,
    "HealingCandidate": HealingCandidate,
    "HealingSignals": HealingSignals,
}


def export_schemas(output_dir: str | Path = "engine/schema") -> None:
    """
    Write one JSON Schema file per exported model to *output_dir*.

    Files are named ``<ModelName>.json`` and conform to JSON Schema draft 2020-12
    as generated by Pydantic v2's ``model_json_schema()``.

    Called automatically when this module is run as ``python -m engine.schemas``.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for name, model in _EXPORTED_MODELS.items():
        schema: dict[str, Any] = model.model_json_schema()
        schema.setdefault("title", name)
        dest = out / f"{name}.json"
        dest.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        print(f"  wrote {dest}")


if __name__ == "__main__":
    import sys

    output_dir = sys.argv[1] if len(sys.argv) > 1 else "engine/schema"
    print(f"Exporting schemas to {output_dir}/")
    export_schemas(output_dir)
    print("Done.")
