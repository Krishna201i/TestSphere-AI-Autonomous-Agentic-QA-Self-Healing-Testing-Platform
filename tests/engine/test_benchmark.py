"""
tests/engine/test_benchmark.py
==============================
Fast smoke test for engine.benchmark — runs 3 mutants, finishes under 60s.

Checks:
- Benchmark produces correctly-shaped records
- Aggregate keys all present
- outcome_on is valid
- confidence in [0, 1]
- Non-healable mutants never report false_heal=True
- CSV and MD files are written with correct structure
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure mutants are generated before importing benchmark
from tests.engine.mutations import MANIFEST_PATH, generate

if not MANIFEST_PATH.exists():
    generate()

from engine.benchmark import (
    _DEMO_APP,
    _MUTATIONS_DIR,
    _compute_aggregate,
    _benchmark_mutant,
    _run_baseline,
    _start_server,
    _stop_server,
    _write_csv,
    _write_md,
)
from engine.schemas import EngineConfig
from playwright.async_api import async_playwright

_MANIFEST: list[dict] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
_SUBSET = _MANIFEST[:3]

_CONFIG = EngineConfig(
    heal_threshold=0.75,
    headless=True,
    artifacts_dir="artifacts/benchmark_test",
    tracing_enabled=False,
)


# ---------------------------------------------------------------------------
# Module-scoped async fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def benchmark_records(event_loop):
    """Run baseline + 3 mutants once, reused by all tests."""

    async def _run():
        base_server, _, base_url = _start_server(_DEMO_APP)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                enriched = await _run_baseline(base_url, _CONFIG, browser)
                records = []
                for m in _SUBSET:
                    rec = await _benchmark_mutant(m, enriched, _CONFIG, browser)
                    records.append(rec)
                return records
            finally:
                await browser.close()
                _stop_server(base_server)

    return event_loop.run_until_complete(_run())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_record_count(benchmark_records):
    assert len(benchmark_records) == len(_SUBSET)


def test_record_schema(benchmark_records):
    required = {
        "name", "change_type", "expected_to_heal",
        "passed_off", "outcome_on", "healed_locator",
        "strategy_used", "confidence", "false_heal",
        "time_per_step_ms_off", "time_per_step_ms_on",
    }
    for rec in benchmark_records:
        assert required <= rec.keys(), f"'{rec['name']}' missing: {required - rec.keys()}"


def test_outcome_on_valid(benchmark_records):
    for rec in benchmark_records:
        assert rec["outcome_on"] in {"passed", "healed", "failed"}, (
            f"'{rec['name']}' bad outcome_on: {rec['outcome_on']!r}"
        )


def test_confidence_in_range(benchmark_records):
    for rec in benchmark_records:
        assert 0.0 <= rec["confidence"] <= 1.0, (
            f"'{rec['name']}' confidence={rec['confidence']}"
        )


def test_time_per_step_non_negative(benchmark_records):
    for rec in benchmark_records:
        assert rec["time_per_step_ms_off"] >= 0
        assert rec["time_per_step_ms_on"] >= 0


def test_non_healable_never_false_heal(benchmark_records):
    for rec in benchmark_records:
        if not rec["expected_to_heal"]:
            assert not rec["false_heal"], (
                f"'{rec['name']}' (non-healable) has false_heal=True"
            )


def test_aggregate_keys(benchmark_records):
    agg = _compute_aggregate(benchmark_records)
    required = {
        "total_mutants", "pass_rate_off", "pass_rate_on",
        "healing_success_rate", "false_heal_rate",
        "correct_refusal_rate", "mean_time_per_step_ms_off",
        "mean_time_per_step_ms_on",
    }
    assert required <= agg.keys()


def test_aggregate_count(benchmark_records):
    agg = _compute_aggregate(benchmark_records)
    assert agg["total_mutants"] == len(_SUBSET)


def test_csv_written(benchmark_records, tmp_path, monkeypatch):
    out = tmp_path / "r.csv"
    monkeypatch.setattr("engine.benchmark._OUT_CSV", out)
    _write_csv(benchmark_records)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(benchmark_records) + 1  # header + N rows


def test_md_written(benchmark_records, tmp_path, monkeypatch):
    out = tmp_path / "r.md"
    monkeypatch.setattr("engine.benchmark._OUT_MD", out)
    _write_md(benchmark_records, _compute_aggregate(benchmark_records))
    content = out.read_text(encoding="utf-8")
    assert "## Aggregate" in content
    assert "## Per-Mutant Results" in content
