"""Tests for SALC and the distributions behind it."""

import pytest

from eval import metrics
from eval.metrics import Distribution
from tests.test_eval_records import a_record, a_run_set

# --- distributions ---------------------------------------------------------


def test_a_distribution_reports_the_middle_not_the_mean():
    spread = Distribution((1.0, 2.0, 90.0))
    assert spread.median == 2.0
    assert spread.total == 93.0


def test_the_interquartile_range_brackets_the_middle():
    spread = Distribution(tuple(float(n) for n in range(1, 9)))
    lower, upper = spread.quartiles
    assert lower < spread.median < upper
    assert spread.iqr == upper - lower


def test_a_single_observation_has_no_spread():
    spread = Distribution((4.0,))
    assert spread.quartiles == (4.0, 4.0)
    assert spread.iqr == 0.0


def test_an_empty_distribution_is_zero_not_an_error():
    spread = Distribution(())
    assert (spread.n, spread.median, spread.total, spread.spread) == (0, 0.0, 0.0, 0.0)


def test_the_spread_reports_the_largest_over_the_smallest():
    """Run-to-run variance is the thing single runs cannot show."""
    assert Distribution((1.0, 30.0)).spread == 30.0
    assert Distribution((0.0, 5.0)).spread == 0.0


def test_every_per_cell_measure_is_summarised():
    summarised = metrics.distributions((a_record(cost=0.2, tokens=100, reasoning=10),))
    assert set(summarised) == set(metrics.MEASURES)
    assert summarised["cost_usd"].median == 0.2
    assert summarised["reasoning_tokens"].median == 10


# --- SALC ------------------------------------------------------------------


def test_salc_is_cost_over_verified_successes():
    run_set = a_run_set(a_record(cost=1.0), a_record(seed=2, cost=1.0))
    computed = metrics.salc(run_set, "baseline")
    assert computed.verified_count == 2
    assert computed.value == pytest.approx(1.0)


def test_a_failure_raises_the_cost_per_success():
    """Failures show up as cost instead of disappearing."""
    run_set = a_run_set(
        a_record(cost=1.0),
        a_record(seed=2, cost=1.0, verified=False, status="verification_failed"),
    )
    computed = metrics.salc(run_set, "baseline")
    assert computed.verified_count == 1
    assert computed.value == pytest.approx(2.0)


def test_a_budget_stop_is_charged_with_its_cost():
    run_set = a_run_set(
        a_record(cost=1.0),
        a_record(
            seed=2, cost=0.5, verified=False, status="budget_exhausted", error_class="cost_budget"
        ),
    )
    computed = metrics.salc(run_set, "baseline")
    assert computed.cells == 2
    assert computed.model_cost == pytest.approx(1.5)
    assert computed.value == pytest.approx(1.5)


def test_an_api_abort_enters_neither_half_of_the_ratio():
    run_set = a_run_set(
        a_record(cost=1.0),
        a_record(
            seed=2, cost=9.0, verified=False, status="aborted", error_class="credit_exhausted"
        ),
    )
    computed = metrics.salc(run_set, "baseline")
    assert computed.cells == 1
    assert computed.excluded == 1
    assert computed.model_cost == pytest.approx(1.0)
    assert computed.value == pytest.approx(1.0)


def test_an_arm_that_verified_nothing_has_no_ratio():
    """Undefined, not infinite and not zero."""
    run_set = a_run_set(a_record(cost=1.0, verified=False, status="verification_failed"))
    computed = metrics.salc(run_set, "baseline")
    assert computed.value is None
    assert computed.success_rate == 0.0


def test_governance_never_enters_the_success_denominator():
    """The ruling: hidden acceptance and must-invariants decide success, nothing else."""
    run_set = a_run_set(
        a_record(
            cost=1.0,
            verified=True,
            arm_artifacts={
                "transformation_plan": "invalid",
                "transformation_plan_expected": True,
                "bundle_validated": False,
                "bundle_problems": ["error: [tier-approval-missing] ..."],
            },
        )
    )
    computed = metrics.salc(run_set, "baseline")
    assert computed.verified_count == 1
    assert computed.value == pytest.approx(1.0)


def test_the_review_term_is_weighted_by_the_rate():
    run_set = a_run_set(a_record(cost=1.0))
    computed = metrics.salc(run_set, "baseline", human_minutes=30.0, rate_per_hour=100.0)
    assert computed.human_cost == pytest.approx(50.0)
    assert computed.value == pytest.approx(51.0)


def test_unmeasured_review_time_is_not_the_same_as_no_review():
    """It contributes nothing, and the rate sweep says so rather than claiming zero minutes."""
    run_set = a_run_set(a_record(cost=1.0))
    computed = metrics.salc(run_set, "baseline", human_minutes=None, rate_per_hour=200.0)
    assert computed.human_minutes is None
    assert computed.human_cost == 0.0
    swept = metrics.sensitivity(run_set, "baseline")
    assert len(set(swept.values())) == 1


def test_the_rate_sweep_moves_once_review_time_is_measured():
    run_set = a_run_set(a_record(cost=1.0))
    swept = metrics.sensitivity(run_set, "baseline", (0.0, 60.0), human_minutes=60.0)
    assert swept[0.0] == pytest.approx(1.0)
    assert swept[60.0] == pytest.approx(61.0)


def test_the_tools_term_is_carried_even_though_it_is_zero_here():
    run_set = a_run_set(a_record(cost=1.0))
    computed = metrics.salc(run_set, "baseline", tools_cost=4.0)
    assert computed.value == pytest.approx(5.0)


# --- the frontier ----------------------------------------------------------


def cheap_and_good(arm: str, cost: float, verified: int, cells: int = 2) -> list[dict]:
    return [
        a_record(arm=arm, seed=seed + 1, cost=cost, verified=seed < verified)
        for seed in range(cells)
    ]


def test_a_dominated_arm_is_off_the_frontier():
    run_set = a_run_set(*cheap_and_good("baseline", 1.0, 2), *cheap_and_good("lcir", 2.0, 2))
    summaries = metrics.summarise(run_set)
    assert metrics.pareto_frontier(summaries) == ["baseline"]


def test_an_arm_that_costs_more_but_succeeds_more_stays_on_the_frontier():
    run_set = a_run_set(*cheap_and_good("baseline", 1.0, 1), *cheap_and_good("lcir", 2.0, 2))
    assert set(metrics.pareto_frontier(metrics.summarise(run_set))) == {"baseline", "lcir"}


def test_identical_arms_both_stay_on_the_frontier():
    run_set = a_run_set(*cheap_and_good("baseline", 1.0, 2), *cheap_and_good("lcir", 1.0, 2))
    assert set(metrics.pareto_frontier(metrics.summarise(run_set))) == {"baseline", "lcir"}


def test_a_frontier_decided_inside_the_noise_says_so():
    """Dominance compares medians; on a small set that can be a difference in nothing."""
    run_set = a_run_set(
        a_record(arm="baseline", seed=1, cost=0.10),
        a_record(arm="baseline", seed=2, cost=0.30),
        a_record(arm="lcir", seed=1, cost=0.11),
        a_record(arm="lcir", seed=2, cost=0.31),
    )
    summaries = metrics.summarise(run_set)
    frontier = metrics.pareto_frontier(summaries)
    caveats = metrics.frontier_caveats(summaries, frontier)
    assert caveats
    assert "not established" in caveats[0]


def test_a_frontier_decided_outside_the_noise_carries_no_caveat():
    run_set = a_run_set(
        a_record(arm="baseline", seed=1, cost=0.10),
        a_record(arm="baseline", seed=2, cost=0.11),
        a_record(arm="lcir", seed=1, cost=9.0),
        a_record(arm="lcir", seed=2, cost=9.1),
    )
    summaries = metrics.summarise(run_set)
    assert metrics.frontier_caveats(summaries, metrics.pareto_frontier(summaries)) == []


def test_overlapping_distributions_are_recognised():
    assert metrics.overlapping(Distribution((1.0, 2.0, 3.0)), Distribution((2.0, 3.0, 4.0)))
    assert not metrics.overlapping(Distribution((1.0, 1.1, 1.2)), Distribution((9.0, 9.1, 9.2)))


def test_summarising_covers_every_arm_present():
    run_set = a_run_set(a_record(arm="baseline"), a_record(arm="compressed"))
    assert [summary.arm for summary in metrics.summarise(run_set)] == ["baseline", "compressed"]
