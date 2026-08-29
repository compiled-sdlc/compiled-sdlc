"""Projecting what a run will cost before it is launched.

The owner runs on a small prepaid balance, so a run has to be priced before it
starts rather than discovered halfway through. This takes an observed per-cell
cost distribution and a matrix size and says what to expect, what to budget for,
and what the ceiling is if everything goes badly.

Three figures, because they answer different questions. The expected total is
the median cell times the cells — what it will probably cost. The budgeted total
applies a stated safety factor to that, and is the number to check a balance
against. The ceiling is the per-cell cost limit times the cells — what the run
cannot exceed, because the executor enforces that limit itself.

The safety factor is stated, never hidden in a constant: a projection whose
margin is invisible is a projection nobody can argue with.

The difficulty multiplier is the second stated assumption. Observed costs come
from whatever has been run so far, and the pilot's change requests were single
endpoint changes that every arm solved; the set they are projecting is
deliberately harder. There is no way to know the factor before running the
harder set, so it is not guessed at — the projection is bracketed, and the
brackets are reported side by side so the reader sees the range rather than one
number with a hidden assumption inside it.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

from eval import records as records_module
from eval.metrics import Distribution
from pipelines.common import executor, locks
from pipelines.common.runner import ARMS

DEFAULT_SAFETY_FACTOR = 1.5

#: What the harder set might cost per cell relative to what has been observed.
#: Reported side by side rather than resolved, because nothing observed yet
#: settles it.
DEFAULT_BRACKETS = (1.0, 2.0, 3.0)


@dataclass(frozen=True)
class Projection:
    """What a matrix of this size is expected to cost."""

    cells: int
    observed: Distribution
    safety_factor: float
    ceiling_per_cell: float
    reserve: float = 0.0
    #: How much more a cell of the projected set is assumed to cost than a cell
    #: of the set the observation came from. One means "the same".
    difficulty_multiplier: float = 1.0

    @property
    def per_cell(self) -> float:
        return self.observed.median * self.difficulty_multiplier

    @property
    def expected(self) -> float:
        return self.per_cell * self.cells

    @property
    def budgeted(self) -> float:
        return self.expected * self.safety_factor

    @property
    def pessimistic(self) -> float:
        """From the upper quartile rather than the middle: a bad but real run."""
        return self.observed.quartiles[1] * self.difficulty_multiplier * self.cells

    @property
    def ceiling(self) -> float:
        return self.ceiling_per_cell * self.cells

    def affordable(self, balance: float) -> bool:
        return self.budgeted <= balance - self.reserve

    def to_dict(self) -> dict:
        return {
            "cells": self.cells,
            "observed_cells": self.observed.n,
            "observed_median_usd": round(self.observed.median, 6),
            "observed_q3_usd": round(self.observed.quartiles[1], 6),
            "safety_factor": self.safety_factor,
            "difficulty_multiplier": self.difficulty_multiplier,
            "projected_per_cell_usd": round(self.per_cell, 6),
            "expected_usd": round(self.expected, 4),
            "budgeted_usd": round(self.budgeted, 4),
            "pessimistic_usd": round(self.pessimistic, 4),
            "ceiling_usd": round(self.ceiling, 4),
            "reserve_usd": self.reserve,
        }

    def render(self) -> str:
        lines = [
            f"matrix            {self.cells} cells",
            f"observed          {self.observed.n} cell(s), median ${self.observed.median:.4f}, "
            f"q3 ${self.observed.quartiles[1]:.4f}",
            f"difficulty        x{self.difficulty_multiplier:g} on the observed median "
            f"(${self.per_cell:.4f} per cell)",
            f"expected          ${self.expected:.2f}  (per-cell x cells)",
            f"budgeted          ${self.budgeted:.2f}  "
            f"(expected x {self.safety_factor:g} safety factor)",
            f"pessimistic       ${self.pessimistic:.2f}  (upper quartile x cells)",
            f"ceiling           ${self.ceiling:.2f}  "
            f"(${self.ceiling_per_cell:g} per-cell limit x cells, executor-enforced)",
        ]
        if self.reserve:
            lines.append(f"reserve held back  ${self.reserve:.2f}")
        return "\n".join(lines)


def matrix_size(change_requests: int, seeds: int, arms: int = len(ARMS)) -> int:
    return change_requests * seeds * arms


def observed_costs(run_set: records_module.RunSet, arm: str | None = None) -> Distribution:
    """The per-cell cost distribution to project from."""
    chosen = run_set.for_arm(arm) if arm else run_set.counted
    return Distribution(tuple(record.get("cost_usd", 0.0) for record in chosen))


def project(
    change_requests: int,
    seeds: int,
    observed: Distribution,
    *,
    arms: int = len(ARMS),
    safety_factor: float = DEFAULT_SAFETY_FACTOR,
    ceiling_per_cell: float | None = None,
    reserve: float = 0.0,
    difficulty_multiplier: float = 1.0,
) -> Projection:
    """What a matrix of this shape is expected to cost, given what has been seen."""
    if observed.n == 0:
        raise ValueError("no observed cells to project from")
    if safety_factor < 1:
        raise ValueError("a safety factor below one is a discount, not a margin")
    if difficulty_multiplier <= 0:
        raise ValueError("a difficulty multiplier must be positive")
    limit = (
        ceiling_per_cell if ceiling_per_cell is not None else executor.Budget.pinned().max_cost_usd
    )
    return Projection(
        cells=matrix_size(change_requests, seeds, arms),
        observed=observed,
        safety_factor=safety_factor,
        ceiling_per_cell=limit,
        reserve=reserve,
        difficulty_multiplier=difficulty_multiplier,
    )


def bracket_table(projections: list[Projection], balance: float | None) -> str:
    """The same matrix at several difficulty assumptions, side by side."""
    header = (
        f"{'difficulty':>10s} {'per cell':>10s} {'expected':>11s} {'budgeted':>11s} "
        f"{'pessimistic':>12s}"
    )
    if balance is not None:
        header += f"  {'against balance':<18s}"
    lines = [header, "-" * len(header)]
    for projection in projections:
        row = (
            f"{'x' + format(projection.difficulty_multiplier, 'g'):>10s} "
            f"${projection.per_cell:9.4f} ${projection.expected:10.2f} "
            f"${projection.budgeted:10.2f} ${projection.pessimistic:11.2f}"
        )
        if balance is not None:
            headroom = balance - projection.reserve - projection.budgeted
            verdict = "covered" if projection.affordable(balance) else "NOT covered"
            row += f"  {verdict:<11s} {headroom:+8.2f}"
        lines.append(row)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project what a run will cost.")
    parser.add_argument("--change-requests", type=int, required=True)
    parser.add_argument("--seeds", type=int, required=True)
    parser.add_argument("--arms", type=int, default=len(ARMS))
    parser.add_argument("--safety-factor", type=float, default=DEFAULT_SAFETY_FACTOR)
    parser.add_argument(
        "--difficulty-multiplier",
        type=float,
        help="assume a cell of the projected set costs this much more than an observed one",
    )
    parser.add_argument(
        "--brackets",
        type=float,
        nargs="*",
        help=(
            "report the matrix at several difficulty multipliers side by side "
            f"(default {' '.join(format(value, 'g') for value in DEFAULT_BRACKETS)})"
        ),
    )
    parser.add_argument("--reserve", type=float, default=0.0, help="held back from the balance")
    parser.add_argument("--balance", type=float, help="check the projection against a balance")
    parser.add_argument("--arm", choices=ARMS, help="project from one arm's costs only")
    parser.add_argument("--runs", type=Path, default=records_module.RUNS_DIR)
    arguments = parser.parse_args(argv)

    run_set = records_module.load(arguments.runs)
    if not run_set.counted:
        print(f"no recorded cells under {arguments.runs} to project from")
        return 1

    observed = observed_costs(run_set, arguments.arm)

    def at(multiplier: float) -> Projection:
        return project(
            arguments.change_requests,
            arguments.seeds,
            observed,
            arms=arguments.arms,
            safety_factor=arguments.safety_factor,
            reserve=arguments.reserve,
            difficulty_multiplier=multiplier,
        )

    print(f"projected from {run_set.label}")
    print(f"prices captured {locks.pricing()['captured_on']}")

    if arguments.brackets is None:
        projection = at(arguments.difficulty_multiplier or 1.0)
        print()
        print(projection.render())
        if arguments.balance is not None:
            verdict = (
                "covers it" if projection.affordable(arguments.balance) else "DOES NOT cover it"
            )
            headroom = arguments.balance - arguments.reserve - projection.budgeted
            print(
                f"\nbalance ${arguments.balance:.2f} {verdict} "
                f"(headroom ${headroom:.2f} after the reserve)"
            )
            return 0 if projection.affordable(arguments.balance) else 1
        return 0

    brackets = tuple(arguments.brackets or DEFAULT_BRACKETS)
    projections = [at(multiplier) for multiplier in brackets]
    reference = projections[0]
    print(
        f"matrix          {reference.cells} cells "
        f"({arguments.change_requests} change requests x {arguments.arms} arms "
        f"x {arguments.seeds} seed(s))"
    )
    print(
        f"observed        {observed.n} cell(s), median ${observed.median:.4f}, "
        f"q3 ${observed.quartiles[1]:.4f}"
    )
    print(f"safety factor   x{arguments.safety_factor:g} applied to expected")
    print(
        f"ceiling         ${reference.ceiling:.2f} "
        f"(${reference.ceiling_per_cell:g} per-cell limit x cells, executor-enforced)"
    )
    if arguments.reserve:
        print(f"reserve         ${arguments.reserve:.2f} held back from the balance")
    print()
    print(bracket_table(projections, arguments.balance))
    print()
    print("The difficulty multiplier is an assumption, not an observation: the")
    print("change requests being projected are harder than the ones observed, and")
    print("nothing run so far says by how much.")
    if arguments.balance is not None:
        covered = [p for p in projections if p.affordable(arguments.balance)]
        if not covered:
            print(f"\nNo bracket is covered by ${arguments.balance:.2f}.")
            return 1
        print(
            f"\n${arguments.balance:.2f} covers the matrix up to "
            f"x{covered[-1].difficulty_multiplier:g} difficulty."
        )
        return 0 if len(covered) == len(projections) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
