"""Uncertainty for the comparison, resampled at the level the design varies.

The cells of this experiment are not independent draws. Twelve of them --- four
protocols by three repetitions --- come from one change request, and change
requests differ enormously in how much work they are. Treating two hundred and
forty cells as two hundred and forty independent observations would report a
precision the design does not have.

So the bootstrap resamples *change requests*, with replacement, and takes each
one whole: every protocol and every repetition of it travels together. That
keeps the pairing the design was built around --- each protocol met exactly the
same twenty tasks --- and lets the resampling express the thing that actually
varies, which is which tasks you happened to choose.

Verified success is compared the same way but paired within a change request:
for each task, protocol A's successes out of three against protocol B's. A
paired comparison is the right one here because the tasks are common to both,
and an unpaired test would spend its power rediscovering that some tasks are
harder than others.

Percentile intervals, not standard errors: the statistics here are ratios and
medians of small skewed samples, and a symmetric interval around them would
promise a shape the data does not have.
"""

import random
import statistics
from dataclasses import dataclass

from eval.records import RunSet

#: Enough that the interval is stable to the cent at two decimals, and cheap.
RESAMPLES = 10000

#: Fixed so a reported interval is reproducible. Recorded beside every result.
BOOTSTRAP_SEED = 20260831


@dataclass(frozen=True)
class Interval:
    """A point estimate and the range the resampling put around it."""

    point: float
    low: float
    high: float
    resamples: int = RESAMPLES

    @property
    def excludes_zero(self) -> bool:
        return (self.low > 0) or (self.high < 0)

    @property
    def excludes_one(self) -> bool:
        """For a ratio: whether the interval keeps clear of no-difference."""
        return (self.low > 1.0) or (self.high < 1.0)

    def to_dict(self) -> dict:
        return {
            "point": round(self.point, 4),
            "ci_low": round(self.low, 4),
            "ci_high": round(self.high, 4),
            "resamples": self.resamples,
        }


def by_task(run_set: RunSet) -> dict[str, list[dict]]:
    """Every cell, grouped by the change request it belongs to."""
    grouped: dict[str, list[dict]] = {}
    for record in run_set.counted:
        grouped.setdefault(record["change_request"], []).append(record)
    return grouped


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(int(fraction * (len(ordered) - 1)), len(ordered) - 1)
    return ordered[index]


def clustered_bootstrap(
    run_set: RunSet, statistic, resamples: int = RESAMPLES, seed: int = BOOTSTRAP_SEED
) -> Interval | None:
    """Resample whole change requests and recompute `statistic` on each draw.

    `statistic` takes the list of cells in a draw and returns a number, or None
    when the draw cannot support it --- an arm that verified nothing in the draw,
    for instance. Draws that return None are dropped rather than counted as
    zero, and the interval says how many draws it rests on.
    """
    tasks = by_task(run_set)
    names = sorted(tasks)
    if not names:
        return None
    point = statistic([cell for name in names for cell in tasks[name]])
    if point is None:
        return None
    chooser = random.Random(seed)
    draws: list[float] = []
    for _ in range(resamples):
        drawn = [chooser.choice(names) for _ in names]
        cells = [cell for name in drawn for cell in tasks[name]]
        value = statistic(cells)
        if value is not None:
            draws.append(value)
    if not draws:
        return None
    return Interval(
        point=point,
        low=_percentile(draws, 0.025),
        high=_percentile(draws, 0.975),
        resamples=len(draws),
    )


# --- the statistics themselves ---------------------------------------------


def mean_cost(arm: str):
    """Mean model cost per cell for one protocol."""

    def compute(cells: list[dict]) -> float | None:
        costs = [c.get("cost_usd", 0.0) for c in cells if c["arm"] == arm]
        return statistics.fmean(costs) if costs else None

    return compute


def cost_ratio(dearer: str, cheaper: str):
    """How many times as much one protocol costs per cell as another."""

    def compute(cells: list[dict]) -> float | None:
        top = [c.get("cost_usd", 0.0) for c in cells if c["arm"] == dearer]
        bottom = [c.get("cost_usd", 0.0) for c in cells if c["arm"] == cheaper]
        if not top or not bottom:
            return None
        low = statistics.fmean(bottom)
        return statistics.fmean(top) / low if low else None

    return compute


def adjusted_cost(arm: str):
    """Success-adjusted model cost: what one verified change cost."""

    def compute(cells: list[dict]) -> float | None:
        mine = [c for c in cells if c["arm"] == arm]
        verified = sum(1 for c in mine if c.get("verified_success"))
        if not mine or not verified:
            return None
        return sum(c.get("cost_usd", 0.0) for c in mine) / verified

    return compute


def adjusted_cost_ratio(dearer: str, cheaper: str):
    def compute(cells: list[dict]) -> float | None:
        top = adjusted_cost(dearer)(cells)
        bottom = adjusted_cost(cheaper)(cells)
        if top is None or bottom is None or not bottom:
            return None
        return top / bottom

    return compute


def paired_success_difference(better: str, worse: str):
    """Mean within-task difference in verified successes, as a rate.

    Paired inside a change request: both protocols met the same task, so the
    task's difficulty cancels instead of being resampled as noise.
    """

    def compute(cells: list[dict]) -> float | None:
        tasks: dict[str, dict[str, list[bool]]] = {}
        for cell in cells:
            if cell["arm"] in (better, worse):
                slot = tasks.setdefault(cell["change_request"], {better: [], worse: []})
                slot[cell["arm"]].append(bool(cell.get("verified_success")))
        differences = []
        for slot in tasks.values():
            if slot[better] and slot[worse]:
                differences.append(statistics.fmean(slot[better]) - statistics.fmean(slot[worse]))
        return statistics.fmean(differences) if differences else None

    return compute


# --- within-task variability ------------------------------------------------


def within_task_spread(run_set: RunSet, arm: str) -> dict:
    """Cost spread among repetitions of the *same* change request.

    The thirtyfold figure in the literature is run-to-run variance on one task.
    Comparing it with the spread across a whole protocol would compare the
    variability of repeating a task with the variability of the task set, which
    is a different and much larger quantity. This is the former: the ratio of
    the dearest to the cheapest repetition within each change request,
    summarised over change requests.
    """
    ratios = []
    for cells in by_task(run_set).values():
        costs = [c.get("cost_usd", 0.0) for c in cells if c["arm"] == arm]
        if len(costs) > 1 and min(costs) > 0:
            ratios.append(max(costs) / min(costs))
    if not ratios:
        return {"arm": arm, "tasks": 0}
    ordered = sorted(ratios)
    return {
        "arm": arm,
        "tasks": len(ordered),
        "median_ratio": round(statistics.median(ordered), 2),
        "max_ratio": round(ordered[-1], 2),
        "q3_ratio": round(_percentile(ordered, 0.75), 2),
    }


def success_rate_interval(run_set: RunSet, arm: str, **kwargs) -> Interval | None:
    """A protocol's verified-success rate, with the change-request clustering kept."""

    def compute(cells: list[dict]) -> float | None:
        mine = [c for c in cells if c["arm"] == arm]
        if not mine:
            return None
        return sum(1 for c in mine if c.get("verified_success")) / len(mine)

    return clustered_bootstrap(run_set, compute, **kwargs)


# --- cache-neutral pricing --------------------------------------------------


def neutral_cost(record: dict, input_rate: float, output_rate: float) -> float:
    """What a cell would have cost with no caching discount at all.

    Prompt caching is an optimisation of the execution, not a property of the
    protocol, and a protocol whose prompt happens to cache better would look
    cheaper for a reason the comparison is not about. Repricing every input
    class --- uncached input, cache writes, cache reads --- at the uncached
    input rate removes the discount entirely and asks whether the ordering
    survives it.

    Both models' tokens are priced at the main model's rate here; the internal
    model is well under one per cent of spend, and the approximation moves every
    protocol the same way.
    """
    usage = record["usage"]
    inputs = (
        usage["input_tokens"]
        + usage["cache_creation_input_tokens"]
        + usage["cache_read_input_tokens"]
    )
    return (inputs * input_rate + usage["output_tokens"] * output_rate) / 1_000_000


def neutral_adjusted_cost(arm: str, input_rate: float, output_rate: float):
    """Cache-neutral cost per verified run, for one protocol."""

    def compute(cells: list[dict]) -> float | None:
        mine = [c for c in cells if c["arm"] == arm]
        verified = sum(1 for c in mine if c.get("verified_success"))
        if not mine or not verified:
            return None
        return sum(neutral_cost(c, input_rate, output_rate) for c in mine) / verified

    return compute


def neutral_ratio(dearer: str, cheaper: str, input_rate: float, output_rate: float):
    def compute(cells: list[dict]) -> float | None:
        top = neutral_adjusted_cost(dearer, input_rate, output_rate)(cells)
        bottom = neutral_adjusted_cost(cheaper, input_rate, output_rate)(cells)
        if top is None or bottom is None or not bottom:
            return None
        return top / bottom

    return compute
