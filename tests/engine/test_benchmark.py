"""
tests/engine/test_benchmark.py
==============================
Fast smoke test for engine.benchmark.

Runs the benchmark against the first 3 mutants only (--subset 3) so the
test suite completes well under 60 seconds even on slow CI.

Checks:
- benchmark runs without error
- records has correct shape
- aggregate keys are all present
- CSV and MD files are written
- outcome_on is one of: passed / healed / failed
- no false-heals on the non-healable mutants (correct-refusal rate = 100%)
  (we only verify the field is not True for non-healable ones)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

# Ensure mutants exist before importing benchmark
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
    _OUT_CSV,
    _OUT_MD,
)
from engine.schemas import RunOptions

_MANIFEST: list[dict] = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

# Use first 3 mutants — mix of healable + non-healable if available
_SUBSET = _MANIFEST[:3]

_OPTIONS = RunOptions(
    headless=True,
    heal_threshold=0.75,
    artifacts_dir="artifacts/benchmark_test",
    tracing_enabled=False,
)


@pytest.fixture(scope="module")
def event_loop():
    """Module-scoped event loop for async fixtures."""
    import asyncio
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def benchmark_records(event_loop):
    """Run baseline + 3 mutants once, share across all tests."""

    async def _run():
        base_server, base_port, base_url = _start_server(_DEMO_APP)
        try:
            enriched_plan = await _run_baseline(base_url, _OPTIONS)
            records = []
            for m in _SUBSET:
                rec = await _benchmark_mutant(m, enriched_plan, _OPTIONS, base_url)
                records.append(rec)
            return records
        finally:
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
        missing = required - rec.keys()
        assert not missing, f"Record for '{rec['name']}' missing fields: {missing}"


def test_outcome_on_valid_values(benchmark_records):
    valid = {"passed", "healed", "failed"}
    for rec in benchmark_records:
        assert rec["outcome_on"] in valid, (
            f"'{rec['name']}' has invalid outcome_on: {rec['outcome_on']!r}"
        )


def test_confidence_in_range(benchmark_records):
    for rec in benchmark_records:
        assert 0.0 <= rec["confidence"] <= 1.0, (
            f"'{rec['name']}' confidence out of range: {rec['confidence']}"
        )


def test_time_per_step_positive(benchmark_records):
    for rec in benchmark_records:
        assert rec["time_per_step_ms_off"] >= 0
        assert rec["time_per_step_ms_on"] >= 0


def test_no_false_heal_on_non_healable(benchmark_records):
    for rec in benchmark_records:
        if not rec["expected_to_heal"]:
            assert not rec["false_heal"], (
                f"'{rec['name']}' (non-healable) reported false_heal=True"
            )


def test_aggregate_keys(benchmark_records):
    agg = _compute_aggregate(benchmark_records)
    required_keys = {
        "total_mutants",
        "pass_rate_off",
        "pass_rate_on",
        "healing_success_rate",
        "false_heal_rate",
        "correct_refusal_rate",
        "mean_time_per_step_ms_off",
        "mean_time_per_step_ms_on",
    }
    assert required_keys <= agg.keys()


def test_aggregate_total(benchmark_records):
    agg = _compute_aggregate(benchmark_records)
    assert agg["total_mutants"] == len(_SUBSET)


def test_csv_written(benchmark_records, tmp_path, monkeypatch):
    """CSV is written with correct header and row count."""
    out = tmp_path / "results.csv"
    monkeypatch.setattr("engine.benchmark._OUT_CSV", out)
    _write_csv(benchmark_records)
    assert out.exists()
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(benchmark_records) + 1  # header + rows


def test_md_written(benchmark_records, tmp_path, monkeypatch):
    """MD file is written and contains the aggregate section."""
    out = tmp_path / "results.md"
    monkeypatch.setattr("engine.benchmark._OUT_MD", out)
    agg = _compute_aggregate(benchmark_records)
    _write_md(benchmark_records, agg)
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "## Aggregate" in content
    assert "## Per-Mutant Results" in content
