"""The pilot table, computed from the recorded runs.

A first cut of `make eval`: what each arm spent and what it got for it, read
back out of runs/ rather than from anything held in memory during a run. Every
figure here is recomputed from the records, so the table can be regenerated at
any time and will say the same thing.

Two rules decide what counts, and they are the ones fixed for the whole
experiment. A cell that spent its budget without finishing is charged to its
arm: the budget is a condition of the experiment, identical for every arm, so an
agent that runs out of it has failed the change request. A cell the API would
not serve — an exhausted balance, a rate limit — measures nothing about any arm
and is left out of every column.

The last column is the shape the paper's metric takes: cost divided by verified
successes, so that retries and failures show up as cost instead of disappearing.
It is not the full measure — the human-review term is not in it — and pilot
numbers validate the harness and go no further.
"""

import argparse
import statistics
from pathlib import Path

from pipelines.common import locks, telemetry
from pipelines.common.runner import ARMS

RUNS_DIR = locks.REPO_ROOT / "runs"

HEADER = (
    f"{'arm':13s} {'cells':>5s} {'ok':>4s} {'fail':>4s} {'excl':>4s} "
    f"{'tokens':>10s} {'cost $':>8s} {'total $':>8s} {'turns':>6s} {'wall s':>7s} "
    f"{'$/verified':>11s}"
)


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def rows(records: list[dict], arms: list[str]) -> list[dict]:
    """One row per arm, from the records of its cells."""
    table = []
    for arm in arms:
        cells = [record for record in records if record.get("arm") == arm]
        counted = [
            record for record in cells if telemetry.counts_towards_the_arm(record.get("status", ""))
        ]
        excluded = len(cells) - len(counted)
        verified = [record for record in counted if record.get("verified_success")]
        total_cost = sum(record.get("cost_usd", 0.0) for record in counted)
        table.append(
            {
                "arm": arm,
                "cells": len(cells),
                "counted": len(counted),
                "verified": len(verified),
                "failed": len(counted) - len(verified),
                "excluded": excluded,
                "tokens": median([record["usage"]["total_tokens"] for record in counted]),
                "cost": median([record.get("cost_usd", 0.0) for record in counted]),
                "total_cost": total_cost,
                "turns": median([record.get("turns", 0) for record in counted]),
                "wall": median([record.get("wall_time_seconds", 0.0) for record in counted]),
                "cost_per_verified": (total_cost / len(verified)) if verified else None,
            }
        )
    return table


def format_table(table: list[dict]) -> str:
    lines = [HEADER, "-" * len(HEADER)]
    for row in table:
        per_verified = (
            f"{row['cost_per_verified']:11.4f}"
            if row["cost_per_verified"] is not None
            else f"{'—':>11s}"
        )
        lines.append(
            f"{row['arm']:13s} {row['cells']:5d} {row['verified']:4d} {row['failed']:4d} "
            f"{row['excluded']:4d} {row['tokens']:10.0f} {row['cost']:8.4f} "
            f"{row['total_cost']:8.4f} {row['turns']:6.0f} {row['wall']:7.0f} {per_verified}"
        )
    return "\n".join(lines)


def by_change_request(records: list[dict], arms: list[str]) -> str:
    """Which change requests any arm managed at all."""
    identifiers = sorted({record["change_request"] for record in records})
    lines = [f"{'change request':16s} " + " ".join(f"{arm:>12s}" for arm in arms)]
    lines.append("-" * len(lines[0]))
    for identifier in identifiers:
        cells = []
        for arm in arms:
            matching = [
                record
                for record in records
                if record["change_request"] == identifier and record["arm"] == arm
            ]
            counted = [
                record
                for record in matching
                if telemetry.counts_towards_the_arm(record.get("status", ""))
            ]
            verified = sum(1 for record in counted if record.get("verified_success"))
            cells.append(f"{verified}/{len(counted)}" if counted else "-")
        lines.append(f"{identifier:16s} " + " ".join(f"{cell:>12s}" for cell in cells))
    return "\n".join(lines)


def failure_reasons(records: list[dict]) -> str:
    """Why cells did not count as successes, so a harness defect is visible as one."""
    reasons: dict[str, int] = {}
    for record in records:
        status = record.get("status", "unknown")
        if status == "completed" and record.get("verified_success"):
            continue
        key = f"{status}/{record.get('error_class') or 'none'}"
        reasons[key] = reasons.get(key, 0) + 1
    if not reasons:
        return "every cell was a verified success"
    return "\n".join(f"  {count:3d}  {reason}" for reason, count in sorted(reasons.items()))


def load(runs_directory: Path) -> list[dict]:
    """Every cell's record, taking the latest record per cell."""
    return sorted(
        telemetry.completed_cells(runs_directory).values(),
        key=lambda record: (record["change_request"], record["arm"], record["seed"]),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the pilot table from the recorded runs.")
    parser.add_argument("--runs", type=Path, default=RUNS_DIR)
    arguments = parser.parse_args(argv)

    records = load(arguments.runs)
    if not records:
        print(f"no runs recorded under {arguments.runs}")
        return 1

    arms = [arm for arm in ARMS if any(record["arm"] == arm for record in records)]
    table = rows(records, arms)

    print(f"{len(records)} cells recorded under {arguments.runs}")
    print(
        f"prices captured {locks.pricing()['captured_on']}; cost recomputed from recorded tokens\n"
    )
    print(format_table(table))
    print("\nverified successes per change request\n")
    print(by_change_request(records, arms))
    print("\nwhy cells did not count as successes\n")
    print(failure_reasons(records))
    print(
        "\nCells the API would not serve are excluded from every column. Budget stops "
        "are charged to the arm.\nMedians across cells; a pilot validates the harness "
        "and its numbers are reported nowhere else."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
