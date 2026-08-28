"""Tests for the cost projection used at the Phase 6 gate."""

import pytest

from eval import projection
from eval.metrics import Distribution
from tests.test_eval_records import a_record, a_run_set

OBSERVED = Distribution((0.10, 0.20, 0.30, 0.40))


def test_the_matrix_is_change_requests_by_seeds_by_arms():
    assert projection.matrix_size(20, 3, arms=4) == 240
    assert projection.matrix_size(5, 2, arms=4) == 40


def test_the_expected_total_is_the_middle_cell_times_the_cells():
    projected = projection.project(2, 1, OBSERVED, arms=1, ceiling_per_cell=2.0)
    assert projected.cells == 2
    assert projected.expected == pytest.approx(0.25 * 2)


def test_the_budgeted_total_applies_the_stated_safety_factor():
    projected = projection.project(2, 1, OBSERVED, arms=1, safety_factor=2.0, ceiling_per_cell=2.0)
    assert projected.budgeted == pytest.approx(projected.expected * 2.0)
    assert projected.to_dict()["safety_factor"] == 2.0, "the margin is stated, never hidden"


def test_the_pessimistic_total_comes_from_the_upper_quartile():
    projected = projection.project(2, 1, OBSERVED, arms=1, ceiling_per_cell=2.0)
    assert projected.pessimistic == pytest.approx(OBSERVED.quartiles[1] * 2)
    assert projected.pessimistic > projected.expected


def test_the_ceiling_is_what_the_run_cannot_exceed():
    projected = projection.project(3, 1, OBSERVED, arms=1, ceiling_per_cell=2.0)
    assert projected.ceiling == pytest.approx(6.0)
    assert projected.ceiling > projected.budgeted


def test_the_ceiling_defaults_to_the_pinned_per_cell_limit():
    from pipelines.common.executor import Budget

    projected = projection.project(1, 1, OBSERVED, arms=1)
    assert projected.ceiling_per_cell == Budget.pinned().max_cost_usd


def test_a_balance_is_checked_after_the_reserve_is_held_back():
    projected = projection.project(
        2, 1, OBSERVED, arms=1, safety_factor=1.0, ceiling_per_cell=2.0, reserve=1.0
    )
    assert projected.budgeted == pytest.approx(0.5)
    assert projected.affordable(1.5) is True
    assert projected.affordable(1.4) is False, "the reserve is not spendable"


def test_projecting_from_nothing_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="no observed cells"):
        projection.project(5, 3, Distribution(()))


def test_a_safety_factor_below_one_is_refused():
    with pytest.raises(ValueError, match="not a margin"):
        projection.project(5, 3, OBSERVED, safety_factor=0.5)


def test_costs_can_be_taken_from_one_arm_only():
    run_set = a_run_set(
        a_record(arm="baseline", cost=0.1),
        a_record(arm="lcir", cost=1.0),
        a_record(arm="lcir", seed=2, cost=1.0),
    )
    assert projection.observed_costs(run_set, "lcir").median == pytest.approx(1.0)
    assert projection.observed_costs(run_set).median == pytest.approx(1.0)


def test_excluded_cells_do_not_shape_the_projection():
    run_set = a_run_set(
        a_record(cost=1.0),
        a_record(seed=2, cost=99.0, status="aborted", error_class="credit_exhausted"),
    )
    assert projection.observed_costs(run_set).values == (1.0,)


def test_the_rendering_states_every_figure_and_its_basis():
    projected = projection.project(2, 1, OBSERVED, arms=1, ceiling_per_cell=2.0)
    rendered = projected.render()
    for expected in ("expected", "budgeted", "pessimistic", "ceiling", "safety factor"):
        assert expected in rendered


def test_the_command_line_reports_against_a_balance(tmp_path, capsys):
    from pipelines.common.telemetry import RunRecord, Usage

    for seed in (1, 2):
        record = RunRecord(
            run_id=f"CR-101__baseline__seed{seed}",
            change_request="CR-101",
            arm="baseline",
            seed=seed,
            status="completed",
            usage=Usage(),
            cost_usd=0.10,
        )
        record.write(tmp_path / record.run_id)
    code = projection.main(
        [
            "--change-requests",
            "1",
            "--seeds",
            "1",
            "--arms",
            "1",
            "--balance",
            "100",
            "--runs",
            str(tmp_path),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "covers it" in out
    assert "PILOT" in out, "a projection says what it was projected from"


def test_the_command_line_refuses_when_the_balance_falls_short(tmp_path, capsys):
    from pipelines.common.telemetry import RunRecord, Usage

    record = RunRecord(
        run_id="CR-101__baseline__seed1",
        change_request="CR-101",
        arm="baseline",
        seed=1,
        status="completed",
        usage=Usage(),
        cost_usd=5.0,
    )
    record.write(tmp_path / record.run_id)
    code = projection.main(
        ["--change-requests", "10", "--seeds", "3", "--balance", "1", "--runs", str(tmp_path)]
    )
    assert code == 1
    assert "DOES NOT cover it" in capsys.readouterr().out


def test_projecting_with_no_records_is_reported(tmp_path, capsys):
    assert projection.main(["--change-requests", "5", "--seeds", "3", "--runs", str(tmp_path)]) == 1
    assert "no recorded cells" in capsys.readouterr().out
