"""Tests for the pilot table.

The table is where the metric semantics become visible, so the rules are tested
here rather than assumed: budget stops count against an arm, cells the API would
not serve count against nothing, and cost per verified success is total spend
divided by the successes that were actually verified.
"""

from pathlib import Path

import pytest

from eval import pilot
from pipelines.common.telemetry import RunRecord, Usage


def a_record(
    arm: str,
    seed: int = 1,
    status: str = "completed",
    verified: bool = True,
    cost: float = 0.5,
    tokens: int = 1000,
    change_request: str = "CR-101",
    error_class: str | None = None,
) -> dict:
    record = RunRecord(
        run_id=f"{change_request}__{arm}__seed{seed}",
        change_request=change_request,
        arm=arm,
        seed=seed,
        status=status,
        error_class=error_class,
        usage=Usage(input_tokens=tokens, output_tokens=0),
        cost_usd=cost,
        turns=4,
        wall_time_seconds=120.0,
    )
    record.verification = {"verified_success": verified}
    return record.to_dict()


def test_a_verified_run_counts_as_a_success():
    row = pilot.rows([a_record("baseline")], ["baseline"])[0]
    assert (row["cells"], row["verified"], row["failed"], row["excluded"]) == (1, 1, 0, 0)
    assert row["cost_per_verified"] == pytest.approx(0.5)


def test_a_budget_stop_is_charged_to_the_arm():
    """The budget is a condition of the experiment; spending it without finishing is failing."""
    records = [
        a_record("baseline", 1),
        a_record(
            "baseline", 2, status="budget_exhausted", verified=False, error_class="wall_clock"
        ),
    ]
    row = pilot.rows(records, ["baseline"])[0]
    assert row["counted"] == 2
    assert row["failed"] == 1
    assert row["excluded"] == 0
    assert row["total_cost"] == pytest.approx(1.0), "its cost still counts"
    assert row["cost_per_verified"] == pytest.approx(1.0)


def test_an_api_abort_is_excluded_from_every_column():
    records = [
        a_record("lcir", 1),
        a_record(
            "lcir", 2, status="aborted", verified=False, cost=0.3, error_class="credit_exhausted"
        ),
    ]
    row = pilot.rows(records, ["lcir"])[0]
    assert row["cells"] == 2
    assert row["counted"] == 1
    assert row["excluded"] == 1
    assert row["total_cost"] == pytest.approx(0.5), "the aborted cell's spend is not the arm's"
    assert row["cost_per_verified"] == pytest.approx(0.5)


def test_an_arm_with_no_verified_success_has_no_cost_per_success():
    records = [a_record("compressed", 1, status="verification_failed", verified=False)]
    row = pilot.rows(records, ["compressed"])[0]
    assert row["verified"] == 0
    assert row["cost_per_verified"] is None
    assert "—" in pilot.format_table([row])


def test_the_table_reports_medians_not_means():
    records = [
        a_record("baseline", 1, cost=0.1, tokens=100),
        a_record("baseline", 2, cost=0.2, tokens=200),
        a_record("baseline", 3, cost=9.0, tokens=9000),
    ]
    row = pilot.rows(records, ["baseline"])[0]
    assert row["cost"] == pytest.approx(0.2), "an outlier must not drag the middle"
    assert row["tokens"] == pytest.approx(200)
    assert row["total_cost"] == pytest.approx(9.3), "totals are still totals"


def test_the_per_change_request_view_shows_what_each_arm_managed():
    records = [
        a_record("baseline", 1, change_request="CR-101"),
        a_record(
            "baseline", 1, change_request="CR-102", verified=False, status="verification_failed"
        ),
    ]
    rendered = pilot.by_change_request(records, ["baseline"])
    assert "CR-101" in rendered and "1/1" in rendered
    assert "CR-102" in rendered and "0/1" in rendered


def test_failures_are_reported_by_reason_so_a_harness_defect_shows_up():
    records = [
        a_record("baseline", 1, status="aborted", verified=False, error_class="rate_limit"),
        a_record("baseline", 2, status="verification_failed", verified=False),
    ]
    reasons = pilot.failure_reasons(records)
    assert "aborted/rate_limit" in reasons
    assert "verification_failed/none" in reasons


def test_an_empty_runs_directory_is_reported_not_charted(tmp_path, capsys):
    assert pilot.main(["--runs", str(tmp_path)]) == 1
    assert "no runs recorded" in capsys.readouterr().out


def test_the_table_reads_the_records_back_from_disk(tmp_path, capsys):
    for seed in (1, 2):
        record = RunRecord(
            run_id=f"CR-101__baseline__seed{seed}",
            change_request="CR-101",
            arm="baseline",
            seed=seed,
            status="completed",
            usage=Usage(input_tokens=10, output_tokens=5),
            cost_usd=0.25,
        )
        record.verification = {"verified_success": True}
        record.write(tmp_path / record.run_id)
    assert pilot.main(["--runs", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "2 cells recorded" in out
    assert "baseline" in out


def test_only_the_latest_record_of_a_cell_is_counted(tmp_path):
    record = RunRecord(
        run_id="CR-101__baseline__seed1",
        change_request="CR-101",
        arm="baseline",
        seed=1,
        status="completed",
        usage=Usage(),
    )
    record.write(tmp_path / record.run_id)
    assert len(pilot.load(Path(tmp_path))) == 1
