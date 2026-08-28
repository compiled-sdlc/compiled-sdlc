"""Tests for the run matrix: its shape, its resumability, and how it handles failure."""

from pathlib import Path

import pytest

from pipelines.common import changerequests as cr
from pipelines.common import runner, telemetry
from pipelines.common.runner import Cell
from pipelines.common.telemetry import RunRecord, Usage


@pytest.fixture(scope="module")
def requests() -> list[cr.ChangeRequest]:
    return cr.load_all()


def a_record(run_id: str, status: str = "completed", error_class: str | None = None) -> RunRecord:
    change_request, arm, seed = run_id.split("__")
    return RunRecord(
        run_id=run_id,
        change_request=change_request,
        arm=arm,
        seed=int(seed.removeprefix("seed")),
        status=status,
        error_class=error_class,
        usage=Usage(input_tokens=10, output_tokens=5),
    )


def test_the_matrix_is_every_change_request_by_arm_by_seed(requests):
    cells = runner.matrix(requests, list(runner.ARMS), seeds=3)
    assert len(cells) == len(requests) * len(runner.ARMS) * 3
    assert len({cell.run_id for cell in cells}) == len(cells)


def test_the_matrix_order_is_stable(requests):
    """A resumed run has to cover the same ground in the same order."""
    first = [cell.run_id for cell in runner.matrix(requests, list(runner.ARMS), 2)]
    second = [cell.run_id for cell in runner.matrix(requests, list(runner.ARMS), 2)]
    assert first == second


def test_a_run_id_names_its_cell(requests):
    cell = Cell(requests[0], "lcir_no_ast", 2)
    assert cell.run_id == f"{requests[0].id}__lcir_no_ast__seed2"


def test_a_finished_cell_is_not_run_again(tmp_path, requests):
    cells = runner.matrix(requests[:1], ["baseline"], seeds=2)
    a_record(cells[0].run_id).write(tmp_path / cells[0].run_id)
    assert [cell.run_id for cell in runner.pending(cells, tmp_path)] == [cells[1].run_id]


def test_an_aborted_cell_is_not_retried_silently(tmp_path, requests):
    """It stays aborted with the class that ended it until someone clears it."""
    cells = runner.matrix(requests[:1], ["baseline"], seeds=1)
    a_record(cells[0].run_id, "aborted", "credit_exhausted").write(tmp_path / cells[0].run_id)
    assert runner.pending(cells, tmp_path) == []


def test_clearing_a_cell_makes_it_pending_again(tmp_path, requests):
    cells = runner.matrix(requests[:1], ["baseline"], seeds=1)
    directory = tmp_path / cells[0].run_id
    a_record(cells[0].run_id, "aborted", "rate_limit").write(directory)
    (directory / telemetry.RECORD_NAME).unlink()
    assert [cell.run_id for cell in runner.pending(cells, tmp_path)] == [cells[0].run_id]


def test_nothing_is_pending_when_everything_has_finished(tmp_path, requests):
    cells = runner.matrix(requests, list(runner.ARMS), seeds=1)
    for cell in cells:
        a_record(cell.run_id).write(tmp_path / cell.run_id)
    assert runner.pending(cells, tmp_path) == []


# --- failure handling ------------------------------------------------------


def test_repeated_aborts_stop_the_matrix_with_the_rest_still_pending(tmp_path, requests, capsys):
    """A dry balance would otherwise burn every remaining cell."""
    cells = runner.matrix(requests, ["baseline"], seeds=1)
    attempted: list[str] = []

    def failing_cell(cell, runs_directory, **options):
        attempted.append(cell.run_id)
        record = a_record(cell.run_id, "aborted", "credit_exhausted")
        record.write(runs_directory / cell.run_id, index=runs_directory / telemetry.INDEX_NAME)
        return record

    records = runner.run_matrix(cells, tmp_path, abort_limit=2, cell_runner=failing_cell)
    assert len(attempted) == 2, "it gave up rather than working through the whole matrix"
    assert len(records) == 2
    assert "stopping" in capsys.readouterr().out
    assert len(runner.pending(cells, tmp_path)) == len(cells) - 2


def test_an_isolated_abort_does_not_stop_the_matrix(tmp_path, requests):
    cells = runner.matrix(requests, ["baseline"], seeds=1)
    statuses = iter(["aborted", "completed", "aborted", "completed", "completed"])

    def mixed_cell(cell, runs_directory, **options):
        status = next(statuses)
        record = a_record(cell.run_id, status, "rate_limit" if status == "aborted" else None)
        record.write(runs_directory / cell.run_id)
        return record

    records = runner.run_matrix(cells, tmp_path, abort_limit=2, cell_runner=mixed_cell)
    assert len(records) == len(cells)


def test_an_unimplemented_arm_is_a_setup_failure_not_a_crash(tmp_path, requests):
    cell = Cell(requests[0], "lcir", 1)
    record = runner.run_cell(cell, tmp_path)
    assert record.status == "aborted"
    assert record.error_class == "setup_failed"
    assert "not implemented yet" in record.error_detail
    assert (tmp_path / cell.run_id / telemetry.RECORD_NAME).exists()


def test_a_setup_failure_is_recorded_so_the_cell_is_not_silently_skipped(tmp_path, requests):
    cell = Cell(requests[0], "lcir", 1)
    runner.run_cell(cell, tmp_path)
    assert list(telemetry.completed_cells(tmp_path)) == [cell.run_id]


def test_the_arm_registry_names_the_four_arms():
    assert runner.ARMS == ("baseline", "lcir", "lcir_no_ast", "compressed")
    with pytest.raises(ValueError, match="unknown arm"):
        runner.load_arm("something-else")


def test_the_summary_counts_statuses_and_spend():
    records = [
        a_record("CR-101__baseline__seed1"),
        a_record("CR-101__baseline__seed2", "aborted", "rate_limit"),
    ]
    records[0].cost_usd = 0.25
    summary = runner.summarise(records)
    assert "completed=1" in summary and "aborted=1" in summary
    assert "$0.2500" in summary


def test_planning_lists_the_pending_cells_without_running_anything(tmp_path, capsys):
    exit_code = runner.main(
        ["--plan", "--seeds", "1", "--arm", "baseline", "--runs", str(tmp_path)]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "5 cells, 5 pending" in out
    assert "CR-101__baseline__seed1" in out
    assert not list(Path(tmp_path).glob("*/record.json"))


def test_an_unknown_change_request_is_reported(tmp_path, capsys):
    assert runner.main(["--plan", "--change-request", "CR-999", "--runs", str(tmp_path)]) == 2
    assert "no such change request" in capsys.readouterr().err
