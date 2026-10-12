"""
engine/schemas.py
=================
All Pydantic v2 data models for the TestSphere-AI QA Execution Engine.
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
    GOTO = "goto"
    CLICK = "click"
    FILL = "fill"
    PRESS = "press"
    SELECT = "select"
    ASSERT_TEXT = "assert_text"
    ASSERT_VISIBLE = "assert_visible"
    WAIT_FOR = "wait_for"


class StepStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    HEALED = "healed"


class TestStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    HEALED = "healed"


# ---------------------------------------------------------------------------
# Element identity
# ---------------------------------------------------------------------------


class BoundingBox(BaseModel):
    model_config = ConfigDict(frozen=True)

    x: float = Field(..., description="Left edge, pixels from viewport origin")
    y: float = Field(..., description="Top edge, pixels from viewport origin")
    width: float = Field(..., ge=0)
    height: float = Field(..., ge=0)


class ElementFingerprint(BaseModel):
    model_config = ConfigDict(frozen=True)

    tag: str | None = Field(None)
    id: str | None = Field(None)
    classes: list[str] = Field(default_factory=list)
    text: str | None = Field(None)
    role: str | None = Field(None)
    aria_label: str | None = Field(None)
    name: str | None = Field(None)
    placeholder: str | None = Field(None)
    attributes: dict[str, str] = Field(default_factory=dict)
    parent_chain: list[str] = Field(default_factory=list)
    sibling_index: int | None = Field(None)
    bounding_box: BoundingBox | None = Field(None)


class Target(BaseModel):
    description: str = Field(...)
    primary_locator: str = Field(...)
    fallback_locators: list[str] = Field(default_factory=list)
    fingerprint: ElementFingerprint | None = Field(None)


# ---------------------------------------------------------------------------
# Test plan (input)
# ---------------------------------------------------------------------------


class Step(BaseModel):
    step_id: str = Field(...)
    action: ActionType = Field(...)
    target: Target | None = Field(None)
    value: str | None = Field(None)
    expected: str | None = Field(None)
    timeout_ms: int = Field(5_000, ge=0)


class TestPlan(BaseModel):
    test_id: str = Field(...)
    name: str = Field(...)
    base_url: str = Field(...)
    steps: list[Step] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Run configuration
# ---------------------------------------------------------------------------


class EngineConfig(BaseModel):
    heal_threshold: float = Field(0.75, ge=0.0, le=1.0)
    default_timeout_ms: int = Field(5_000, ge=0)
    headless: bool = Field(True)
    artifacts_dir: str = Field("artifacts")
    slow_mo_ms: int = Field(0, ge=0)
    tracing_enabled: bool = Field(False)
    max_candidates: int = Field(20, ge=1)


class RunOptions(BaseModel):
    heal_threshold: float | None = Field(None, ge=0.0, le=1.0)
    default_timeout_ms: int | None = Field(None, ge=0)
    headless: bool | None = None
    artifacts_dir: str | None = None
    slow_mo_ms: int | None = Field(None, ge=0)
    tracing_enabled: bool | None = None
    max_candidates: int | None = Field(None, ge=1)

    def merged(self, base: EngineConfig) -> EngineConfig:
        overrides = {k: v for k, v in self.model_dump().items() if v is not None}
        return base.model_copy(update=overrides)


# ---------------------------------------------------------------------------
# Test results (output)
# ---------------------------------------------------------------------------


class HealingSignals(BaseModel):
    attribute: float = Field(0.0, ge=0.0, le=1.0)
    text: float = Field(0.0, ge=0.0, le=1.0)
    position: float = Field(0.0, ge=0.0, le=1.0)
    structure: float = Field(0.0, ge=0.0, le=1.0)


class HealingCandidate(BaseModel):
    locator: str = Field(...)
    score: float = Field(..., ge=0.0, le=1.0)
    signals: HealingSignals = Field(...)


class HealingReport(BaseModel):
    original_locator: str = Field(...)
    candidates: list[HealingCandidate] = Field(default_factory=list)
    selected_locator: str | None = Field(None)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    strategy_used: str = Field("unknown")


class StepResult(BaseModel):
    step_id: str = Field(...)
    status: StepStatus = Field(...)
    error: str | None = Field(None)
    healing: HealingReport | None = Field(None)
    duration_ms: float = Field(0.0, ge=0.0)
    screenshot: str | None = Field(None)


class TestResult(BaseModel):
    test_id: str = Field(...)
    name: str = Field(...)
    status: TestStatus = Field(...)
    steps: list[StepResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = Field(None)
    error: str | None = Field(None)


def export_schemas(output_dir: str = "schemas") -> None:
    """Export JSON Schemas for all public models."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    for cls in [TestPlan, TestResult, EngineConfig, RunOptions]:
        (out / f"{cls.__name__}.json").write_text(
            json.dumps(cls.model_json_schema(), indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    export_schemas()
