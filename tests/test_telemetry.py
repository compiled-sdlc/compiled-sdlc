"""Tests for run records: their schema, their costing, and resumability."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from pipelines.common import locks, telemetry
from pipelines.common.telemetry import RunRecord, Usage

REPO = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((REPO / "pipelines" / "common" / "run-record.schema.json").read_text())

PRICING = {
    "models": {
        "test-model": {
            "input": 2.0,
            "output": 10.0,
            "cache_write_5m": 2.5,
            "cache_write_1h": 4.0,
            "cache_read": 0.2,
        }
    }
}


def a_record(**overrides) -> RunRecord:
    defaults = {
        "run_id": telemetry.cell_id("CR-101", "baseline", 1),
        "change_request": "CR-101",
        "arm": "baseline",
        "seed": 1,
        "status": "completed",
        "usage": Usage(input_tokens=1000, output_tokens=500, reasoning_tokens=200),
        "cost_usd": 0.007,
        "pricing_captured_on": "2026-08-28",
    }
    return RunRecord(**{**defaults, **overrides})


def test_the_schema_is_valid():
    Draft202012Validator.check_schema(SCHEMA)


def test_a_written_record_validates_against_the_schema(tmp_path):
    record = a_record()
    record.finished_at = telemetry.now()
    record.verification = {"verified_success": True, "invariants": []}
    record.write(tmp_path / record.run_id)
    written = json.loads((tmp_path / record.run_id / "record.json").read_text())
    errors = list(Draft202012Validator(SCHEMA).iter_errors(written))
    assert errors == [], [error.message for error in errors]


def test_the_record_reports_total_tokens_and_verified_success(tmp_path):
    record = a_record(
        usage=Usage(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=10,
            cache_read_input_tokens=5,
        )
    )
    record.verification = {"verified_success": False}
    written = record.to_dict()
    assert written["usage"]["total_tokens"] == 165
    assert written["verified_success"] is False


def test_cost_is_computed_from_tokens_and_the_captured_prices():
    usage = Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert telemetry.compute_cost(usage, "test-model", PRICING) == pytest.approx(12.0)


def test_reasoning_tokens_are_not_priced_a_second_time():
    """They are already inside the output count."""
    plain = Usage(input_tokens=0, output_tokens=1_000_000)
    thinking = Usage(input_tokens=0, output_tokens=1_000_000, reasoning_tokens=900_000)
    assert telemetry.compute_cost(plain, "test-model", PRICING) == telemetry.compute_cost(
        thinking, "test-model", PRICING
    )


def test_cache_tokens_are_priced_at_their_own_rates():
    usage = Usage(
        cache_creation_input_tokens=1_000_000,
        cache_creation_5m_tokens=600_000,
        cache_creation_1h_tokens=400_000,
        cache_read_input_tokens=1_000_000,
    )
    expected = 0.6 * 2.5 + 0.4 * 4.0 + 1.0 * 0.2
    assert telemetry.compute_cost(usage, "test-model", PRICING) == pytest.approx(expected)


def test_cache_creation_without_a_stated_lifetime_is_charged_at_the_shorter_one():
    usage = Usage(cache_creation_input_tokens=1_000_000)
    assert telemetry.compute_cost(usage, "test-model", PRICING) == pytest.approx(2.5)


def test_an_unpriced_model_is_an_error_not_a_zero():
    with pytest.raises(KeyError, match="no captured price"):
        telemetry.compute_cost(Usage(), "unpinned-model", PRICING)


def test_every_pinned_model_can_be_costed():
    for identifier in (
        locks.executor()["model"]["id"],
        locks.executor()["model"]["debug"]["id"],
    ):
        assert telemetry.compute_cost(Usage(input_tokens=1000), identifier) > 0


def test_the_index_accumulates_every_record(tmp_path):
    index = tmp_path / "index.jsonl"
    for seed in (1, 2):
        record = a_record(run_id=telemetry.cell_id("CR-101", "baseline", seed), seed=seed)
        record.write(tmp_path / record.run_id, index=index)
    assert [entry["seed"] for entry in telemetry.read_index(index)] == [1, 2]


def test_completed_cells_are_the_ones_a_rerun_skips(tmp_path):
    finished = a_record()
    finished.write(tmp_path / finished.run_id)
    aborted = a_record(
        run_id=telemetry.cell_id("CR-102", "lcir", 1),
        change_request="CR-102",
        arm="lcir",
        status="aborted",
        error_class="credit_exhausted",
    )
    aborted.write(tmp_path / aborted.run_id)
    assert set(telemetry.completed_cells(tmp_path)) == {finished.run_id, aborted.run_id}


def test_a_cell_still_running_is_not_treated_as_finished(tmp_path):
    running = a_record(status="running")
    running.write(tmp_path / running.run_id)
    assert telemetry.completed_cells(tmp_path) == {}


def test_an_unreadable_record_does_not_stop_the_scan(tmp_path):
    good = a_record()
    good.write(tmp_path / good.run_id)
    broken = tmp_path / "CR-999__baseline__seed1"
    broken.mkdir()
    (broken / "record.json").write_text("{not json")
    assert set(telemetry.completed_cells(tmp_path)) == {good.run_id}


def test_an_abort_is_never_an_agent_failure():
    assert telemetry.ERROR_CLASSES >= telemetry.ABORT_CLASSES
    # Budget stops are decisions of the harness, not failures of the apparatus.
    assert not telemetry.ABORT_CLASSES & {"turn_budget", "cost_budget", "executor_crash"}
