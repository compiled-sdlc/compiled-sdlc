"""Success-adjusted lifecycle cost, and the distributions behind it.

    SALC = (C_model + C_tools + lambda * T_human) / N_verified

Dividing by verified successes is the whole point: an arm that spends twice as
much and fails half as often is not cheaper, and retries and failures show up as
cost instead of disappearing into an average.

Three things decide what goes into it, and all three are fixed elsewhere so that
this module only arithmetic.

`N_verified` counts cells that passed the hidden acceptance checks and violated
no `must` invariant. Nothing else enters it — a governance gap is reported by
the governance index and never docked from success.

A cell that spent its budget without finishing is charged to its arm, cost and
all: the budget is a condition of the experiment, identical for every arm. A
cell the API would not serve is excluded from both halves of the ratio.

`T_human` is not measured yet. The term is carried through with its rate so the
sensitivity analysis is ready, and reported as unmeasured rather than as zero
review time, which would be a different and false claim.
"""

import statistics
from dataclasses import dataclass, field

from eval.records import RunSet

# Rates to sweep the human-time term over, in currency per hour. Only meaningful
# once review time is measured; until then every sweep gives the same answer,
# which is itself worth showing.
DEFAULT_RATES = (0.0, 50.0, 100.0, 200.0)


@dataclass(frozen=True)
class Distribution:
    """A summary that survives an outlier, which single runs do not."""

    values: tuple[float, ...]

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def median(self) -> float:
        return statistics.median(self.values) if self.values else 0.0

    @property
    def quartiles(self) -> tuple[float, float]:
        if len(self.values) < 2:
            single = self.values[0] if self.values else 0.0
            return single, single
        ordered = sorted(self.values)
        lower, _, upper = statistics.quantiles(ordered, n=4)
        return lower, upper

    @property
    def iqr(self) -> float:
        lower, upper = self.quartiles
        return upper - lower

    @property
    def total(self) -> float:
        return sum(self.values)

    @property
    def spread(self) -> float:
        """Largest over smallest — the shape run-to-run variance takes."""
        if not self.values or min(self.values) <= 0:
            return 0.0
        return max(self.values) / min(self.values)

    def to_dict(self) -> dict:
        lower, upper = self.quartiles
        return {
            "n": self.n,
            "median": round(self.median, 6),
            "q1": round(lower, 6),
            "q3": round(upper, 6),
            "iqr": round(self.iqr, 6),
            "min": round(min(self.values), 6) if self.values else 0.0,
            "max": round(max(self.values), 6) if self.values else 0.0,
            "total": round(self.total, 6),
            "spread": round(self.spread, 2),
        }


MEASURES = {
    "cost_usd": lambda record: record.get("cost_usd", 0.0),
    "total_tokens": lambda record: record["usage"]["total_tokens"],
    "input_tokens": lambda record: record["usage"]["input_tokens"],
    "output_tokens": lambda record: record["usage"]["output_tokens"],
    "reasoning_tokens": lambda record: record["usage"]["reasoning_tokens"],
    "turns": lambda record: record.get("turns", 0),
    "wall_time_seconds": lambda record: record.get("wall_time_seconds", 0.0),
}


def distributions(records: tuple[dict, ...]) -> dict[str, Distribution]:
    """Every per-cell measure, summarised."""
    return {
        name: Distribution(tuple(float(read(record)) for record in records))
        for name, read in MEASURES.items()
    }


def verified(records: tuple[dict, ...]) -> tuple[dict, ...]:
    """Cells that passed the hidden checks and violated no must-invariant."""
    return tuple(record for record in records if record.get("verified_success"))


@dataclass(frozen=True)
class Salc:
    """One arm's success-adjusted lifecycle cost."""

    arm: str
    cells: int
    excluded: int
    verified_count: int
    model_cost: float
    tools_cost: float
    human_minutes: float | None
    rate_per_hour: float

    @property
    def human_cost(self) -> float:
        """The weighted review term. Zero while review time is unmeasured."""
        if self.human_minutes is None:
            return 0.0
        return self.rate_per_hour * (self.human_minutes / 60.0)

    @property
    def total_cost(self) -> float:
        return self.model_cost + self.tools_cost + self.human_cost

    @property
    def value(self) -> float | None:
        """None when an arm verified nothing: the ratio is undefined, not infinite."""
        if self.verified_count == 0:
            return None
        return self.total_cost / self.verified_count

    @property
    def success_rate(self) -> float:
        return self.verified_count / self.cells if self.cells else 0.0

    def to_dict(self) -> dict:
        return {
            "arm": self.arm,
            "cells_counted": self.cells,
            "cells_excluded": self.excluded,
            "verified": self.verified_count,
            "success_rate": round(self.success_rate, 4),
            "model_cost_usd": round(self.model_cost, 6),
            "tools_cost_usd": round(self.tools_cost, 6),
            "human_minutes": self.human_minutes,
            "rate_per_hour": self.rate_per_hour,
            "human_cost_usd": round(self.human_cost, 6),
            "total_cost_usd": round(self.total_cost, 6),
            "salc_usd_per_verified": None if self.value is None else round(self.value, 6),
        }


def salc(
    run_set: RunSet,
    arm: str,
    *,
    tools_cost: float = 0.0,
    human_minutes: float | None = None,
    rate_per_hour: float = 0.0,
) -> Salc:
    """SALC for one arm.

    `tools_cost` is the execution cost of the runs. It is zero here because the
    target application is built and run as local processes on the experiment
    machine, with nothing metered; it stays a parameter because that is a fact
    about this deployment, not about the metric.
    """
    counted = run_set.for_arm(arm)
    excluded = sum(1 for record in run_set.excluded if record["arm"] == arm)
    return Salc(
        arm=arm,
        cells=len(counted),
        excluded=excluded,
        verified_count=len(verified(counted)),
        model_cost=sum(record.get("cost_usd", 0.0) for record in counted),
        tools_cost=tools_cost,
        human_minutes=human_minutes,
        rate_per_hour=rate_per_hour,
    )


def sensitivity(
    run_set: RunSet,
    arm: str,
    rates: tuple[float, ...] = DEFAULT_RATES,
    *,
    human_minutes: float | None = None,
    tools_cost: float = 0.0,
) -> dict[float, float | None]:
    """How SALC moves as the review rate moves.

    While review time is unmeasured every rate gives the same answer. That is
    reported rather than hidden: it says the metric currently rests on model
    cost alone, and names what has to be measured before it does not.
    """
    return {
        rate: salc(
            run_set,
            arm,
            tools_cost=tools_cost,
            human_minutes=human_minutes,
            rate_per_hour=rate,
        ).value
        for rate in rates
    }


@dataclass
class ArmSummary:
    """Everything reported about one arm."""

    arm: str
    salc: Salc
    distributions: dict[str, Distribution] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            **self.salc.to_dict(),
            "distributions": {name: value.to_dict() for name, value in self.distributions.items()},
        }


def summarise(run_set: RunSet, **options) -> list[ArmSummary]:
    """One summary per arm, in the order the arms are declared."""
    return [
        ArmSummary(
            arm=arm,
            salc=salc(run_set, arm, **options),
            distributions=distributions(run_set.for_arm(arm)),
        )
        for arm in run_set.arms
    ]


def pareto_frontier(summaries: list[ArmSummary]) -> list[str]:
    """The arms nothing else beats on both cost and verified success.

    An arm is on the frontier when no other arm reached at least its success
    rate for no more cost per cell.
    """
    frontier = []
    for candidate in summaries:
        cost = candidate.distributions["cost_usd"].median
        dominated = any(
            other.arm != candidate.arm
            and other.salc.success_rate >= candidate.salc.success_rate
            and other.distributions["cost_usd"].median <= cost
            and (
                other.salc.success_rate > candidate.salc.success_rate
                or other.distributions["cost_usd"].median < cost
            )
            for other in summaries
        )
        if not dominated:
            frontier.append(candidate.arm)
    return frontier


def overlapping(left: Distribution, right: Distribution) -> bool:
    """Whether two distributions' interquartile ranges overlap."""
    left_low, left_high = left.quartiles
    right_low, right_high = right.quartiles
    return left_low <= right_high and right_low <= left_high


def frontier_caveats(summaries: list[ArmSummary], frontier: list[str]) -> list[str]:
    """Where the frontier separates arms by less than their own spread.

    Dominance is a strict comparison of medians, and on a small run set two arms
    can sit either side of it on a difference well inside the noise. Saying so is
    the difference between a frontier and a ranking.
    """
    by_arm = {summary.arm: summary for summary in summaries}
    caveats = []
    for winner in frontier:
        for summary in summaries:
            if summary.arm in frontier:
                continue
            first = by_arm[winner].distributions["cost_usd"]
            second = summary.distributions["cost_usd"]
            if by_arm[winner].salc.success_rate == summary.salc.success_rate and overlapping(
                first, second
            ):
                caveats.append(
                    f"{winner} is ahead of {summary.arm} by "
                    f"${abs(first.median - second.median):.4f} per cell, which is inside "
                    f"both interquartile ranges: the ordering is not established."
                )
    return caveats
