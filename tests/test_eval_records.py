"""Tests for reading a run set, and for what may be said about one."""

import pytest

from eval import records as records_module
from pipelines.common.telemetry import RunRecord, Usage


def a_record(
    arm: str = "baseline",
    seed: int = 1,
    change_request: str = "CR-101",
    status: str = "completed",
    verified: bool = True,
    cost: float = 0.2,
    tokens: int = 1000,
    reasoning: int = 100,
    turns: int = 10,
    wall: float = 60.0,
    error_class: str | None = None,
    arm_artifacts: dict | None = None,
) -> dict:
    record = RunRecord(
        run_id=f"{change_request}__{arm}__seed{seed}",
        change_request=change_request,
        arm=arm,
        seed=seed,
        status=status,
        error_class=error_class,
        usage=Usage(input_tokens=tokens, output_tokens=0, reasoning_tokens=reasoning),
        cost_usd=cost,
        turns=turns,
        wall_time_seconds=wall,
    )
    record.verification = {"verified_success": verified}
    record.arm_artifacts = arm_artifacts or {}
    return record.to_dict()


def a_run_set(*records: dict) -> records_module.RunSet:
    return records_module.RunSet(records=tuple(records))


def test_a_cell_the_api_would_not_serve_is_excluded():
    run_set = a_run_set(
        a_record(),
        a_record(seed=2, status="aborted", verified=False, error_class="credit_exhausted"),
    )
    assert len(run_set.counted) == 1
    assert len(run_set.excluded) == 1


def test_a_budget_stop_is_counted_against_its_arm():
    run_set = a_run_set(
        a_record(status="budget_exhausted", verified=False, error_class="wall_clock")
    )
    assert len(run_set.counted) == 1
    assert run_set.excluded == ()


def test_the_seed_count_is_the_thinnest_cell():
    """One cell run once is enough to make the whole set a one-seed set."""
    run_set = a_run_set(
        a_record(seed=1),
        a_record(seed=2),
        a_record(change_request="CR-102", seed=1),
    )
    assert run_set.seeds == 1


def test_a_thin_run_set_is_a_pilot_and_says_why():
    run_set = a_run_set(a_record(), a_record(seed=2))
    assert run_set.is_pilot
    assert run_set.label.startswith("PILOT")
    reasons = run_set.why_pilot()
    assert any("seed" in reason for reason in reasons)
    assert any("change request" in reason for reason in reasons)


def test_a_run_set_meeting_the_discipline_is_not_labelled_a_pilot():
    """The label follows the data, so nothing becomes a result by forgetting to say it is not."""
    records = [
        a_record(change_request=f"CR-{100 + n}", seed=seed)
        for n in range(records_module.MANUSCRIPT_CHANGE_REQUESTS)
        for seed in range(1, records_module.MANUSCRIPT_SEEDS + 1)
    ]
    run_set = a_run_set(*records)
    assert not run_set.is_pilot
    assert run_set.why_pilot() == []
    assert run_set.label == records_module.FULL_LABEL


def test_one_seed_short_is_still_a_pilot():
    records = [
        a_record(change_request=f"CR-{100 + n}", seed=seed)
        for n in range(records_module.MANUSCRIPT_CHANGE_REQUESTS)
        for seed in range(1, records_module.MANUSCRIPT_SEEDS + 1)
    ]
    records = [record for record in records if record["run_id"] != records[-1]["run_id"]]
    assert a_run_set(*records).is_pilot


def test_records_are_selected_by_arm_and_by_cell():
    run_set = a_run_set(
        a_record(arm="baseline"),
        a_record(arm="lcir"),
        a_record(arm="lcir", change_request="CR-102"),
    )
    assert len(run_set.for_arm("lcir")) == 2
    assert len(run_set.for_cell("CR-102", "lcir")) == 1
    assert run_set.arms == ("baseline", "lcir")
    assert run_set.change_requests == ("CR-101", "CR-102")


def test_loading_reads_the_records_back_off_disk(tmp_path):
    for seed in (1, 2):
        record = RunRecord(
            run_id=f"CR-101__baseline__seed{seed}",
            change_request="CR-101",
            arm="baseline",
            seed=seed,
            status="completed",
            usage=Usage(input_tokens=10),
        )
        record.write(tmp_path / record.run_id)
    run_set = records_module.load(tmp_path)
    assert len(run_set.records) == 2
    assert run_set.seeds == 2


def test_an_empty_directory_loads_to_nothing(tmp_path):
    assert records_module.load(tmp_path).records == ()


def test_written_summaries_are_stable_json(tmp_path):
    path = records_module.write_json(tmp_path / "out" / "summary.json", {"b": 1, "a": 2})
    assert path.read_text() == '{\n  "a": 2,\n  "b": 1\n}\n'


@pytest.mark.parametrize("status", ["completed", "agent_failed", "verification_failed"])
def test_every_outcome_of_the_agent_counts_towards_the_arm(status):
    assert len(a_run_set(a_record(status=status)).counted) == 1
