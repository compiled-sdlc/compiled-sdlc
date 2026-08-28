"""Tests for the report and the figures: what `make eval` produces."""

import json

import pytest

from eval import figures as figures_module
from eval import metrics, report
from eval import records as records_module
from pipelines.common.telemetry import RunRecord, Usage
from tests.test_eval_records import a_record, a_run_set


def write_records(directory, records: list[dict]) -> None:
    for payload in records:
        record = RunRecord(
            run_id=payload["run_id"],
            change_request=payload["change_request"],
            arm=payload["arm"],
            seed=payload["seed"],
            status=payload["status"],
            usage=Usage(input_tokens=payload["usage"]["input_tokens"]),
            cost_usd=payload["cost_usd"],
            turns=payload["turns"],
            wall_time_seconds=payload["wall_time_seconds"],
        )
        record.verification = {"verified_success": payload["verified_success"]}
        record.arm_artifacts = payload.get("arm_artifacts") or {}
        record.write(directory / record.run_id)


@pytest.fixture
def a_small_run(tmp_path):
    write_records(
        tmp_path,
        [
            a_record(arm="baseline", seed=1, cost=0.10),
            a_record(arm="baseline", seed=2, cost=0.12),
            a_record(
                arm="lcir",
                seed=1,
                cost=0.40,
                arm_artifacts={
                    "transformation_plan": "valid",
                    "transformation_plan_expected": True,
                    "bundle_validated": True,
                    "bundle_problems": [],
                    "tier_required": True,
                    "tier_satisfied": True,
                    "obligations_traced": 1.0,
                    "transformations_attributed": 1.0,
                },
            ),
            a_record(
                arm="lcir",
                seed=2,
                cost=0.44,
                verified=False,
                status="verification_failed",
                arm_artifacts={
                    "transformation_plan": "invalid",
                    "transformation_plan_expected": True,
                    "bundle_validated": False,
                    "bundle_problems": [],
                    "tier_required": True,
                    "tier_satisfied": None,
                },
            ),
        ],
    )
    return tmp_path


# --- the label -------------------------------------------------------------


def test_the_report_labels_a_thin_run_set_a_pilot(a_small_run, capsys):
    assert (
        report.main(
            [
                "--runs",
                str(a_small_run),
                "--no-figures",
                "--summary",
                str(a_small_run / "summary.json"),
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "PILOT" in out
    assert out.strip().endswith("PILOT — harness validation only, not results")
    assert "not results" in out


def test_the_label_cannot_be_overridden_from_the_command_line():
    """Nothing becomes a result by passing a flag."""
    parser_flags = report.main.__doc__ or ""
    assert "--label" not in parser_flags
    with pytest.raises(SystemExit):
        report.main(["--label", "results"])


def test_every_figure_carries_the_label(tmp_path):
    run_set = a_run_set(a_record(arm="baseline", cost=0.1), a_record(arm="lcir", cost=0.4))
    summaries = metrics.summarise(run_set)
    written = figures_module.write_all(summaries, run_set.label, tmp_path)
    assert len(written) == 2
    for path in written:
        assert path.exists() and path.stat().st_size > 1000


def test_the_figures_are_regenerated_not_kept(tmp_path):
    run_set = a_run_set(a_record(arm="baseline"))
    summaries = metrics.summarise(run_set)
    first = figures_module.pareto(summaries, run_set.label, tmp_path)
    first.unlink()
    again = figures_module.pareto(summaries, run_set.label, tmp_path)
    assert again.exists(), "a deleted figure comes back from the records"


# --- the report's own content ----------------------------------------------


def test_the_report_is_built_from_the_records_alone(a_small_run):
    run_set = records_module.load(a_small_run)
    built = report.build(run_set)
    assert built["cells"] == 4
    assert built["counted"] == 4
    assert built["is_pilot"] is True
    assert [entry["arm"] for entry in built["salc"]] == ["baseline", "lcir"]
    assert [entry["arm"] for entry in built["governance"]] == ["baseline", "lcir"]


def test_the_summary_is_written_as_json(a_small_run, capsys):
    destination = a_small_run / "out" / "summary.json"
    report.main(["--runs", str(a_small_run), "--no-figures", "--summary", str(destination)])
    written = json.loads(destination.read_text())
    assert written["is_pilot"] is True
    assert written["pricing_captured_on"]
    assert written["salc"][0]["arm"] == "baseline"


def test_the_salc_table_reports_an_arm_with_no_success_as_undefined():
    run_set = a_run_set(a_record(verified=False, status="verification_failed"))
    assert "undefined" in report.salc_table(metrics.summarise(run_set))


def test_the_governance_table_never_prints_a_zero_for_an_unmeasurable_arm():
    from eval import governance

    run_set = a_run_set(a_record(arm="baseline"))
    rendered = report.governance_table(governance.indices(run_set))
    assert "not observable" in rendered
    assert "0.00" not in rendered


def test_the_outcomes_say_which_cells_were_charged_and_which_excluded():
    run_set = a_run_set(
        a_record(status="aborted", verified=False, error_class="rate_limit"),
        a_record(seed=2, status="budget_exhausted", verified=False, error_class="wall_clock"),
    )
    rendered = report.outcomes(run_set)
    assert "excluded" in rendered
    assert "charged to the arm" in rendered


def test_the_per_change_request_table_shows_successes_and_median_cost():
    run_set = a_run_set(
        a_record(arm="baseline", cost=0.2),
        a_record(arm="baseline", seed=2, cost=0.4, verified=False, status="verification_failed"),
    )
    rendered = report.per_change_request(run_set)
    assert "CR-101" in rendered
    assert "1/2" in rendered


def test_the_sensitivity_table_names_what_is_unmeasured():
    run_set = a_run_set(a_record())
    rendered = report.sensitivity_table(run_set)
    assert "not measured" in rendered


def test_an_empty_run_directory_is_reported_not_charted(tmp_path, capsys):
    assert report.main(["--runs", str(tmp_path), "--no-figures"]) == 1
    assert "no runs recorded" in capsys.readouterr().out


def test_the_whole_report_runs_end_to_end_with_figures(a_small_run, capsys):
    code = report.main(
        [
            "--runs",
            str(a_small_run),
            "--figures",
            str(a_small_run / "figures"),
            "--summary",
            str(a_small_run / "summary.json"),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    for section in (
        "SUCCESS-ADJUSTED LIFECYCLE COST",
        "SENSITIVITY TO THE REVIEW RATE",
        "GOVERNANCE COMPLETENESS",
        "PER-CELL DISTRIBUTIONS",
        "PER CHANGE REQUEST",
        "OUTCOMES",
        "PARETO FRONTIER",
    ):
        assert section in out
    assert len(list((a_small_run / "figures").glob("*.png"))) == 2
