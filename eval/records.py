"""Reading the recorded runs.

Everything the evaluation reports is computed from the run records under
`runs/` and nothing else — not from the bundles a run happened to leave beside
them, not from anything held in memory during a run. A number in the paper has
to be reproducible from the records and the price table they were costed at, so
the records are the only input this package reads.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from pipelines.common import locks, telemetry

RUNS_DIR = locks.REPO_ROOT / "runs"

# What a run set has to be before its numbers are anything but harness
# validation: the experiment's own discipline, three independent repetitions
# full change-request set. Anything short of it is a pilot, and says so.
MANUSCRIPT_SEEDS = 3
MANUSCRIPT_CHANGE_REQUESTS = 15

PILOT_LABEL = "PILOT — harness validation only, not results"
FULL_LABEL = "full run"


# The paper names the conditions by what they vary, not by their code
# identifiers. The identifiers are unchanged in the records and the harness; this
# is the mapping, and it is the only place it is written down.
PROTOCOL = {
    "baseline": "prose-free",
    "compressed": "prose-min",
    "lcir_no_ast": "typed-free",
    "lcir": "typed-plan",
}

#: Repetitions of a cell are independent re-runs under identical conditions.
#: Nothing in the harness passes a sampling seed to the model; the field is
#: named `seed` in the records and means the repetition index.
REPETITION_FIELD = "seed"


@dataclass(frozen=True)
class RunSet:
    """Every recorded cell, and what may be said about it."""

    records: tuple[dict, ...]

    @property
    def counted(self) -> tuple[dict, ...]:
        """Cells that say something about the arm that ran them."""
        return tuple(
            record
            for record in self.records
            if telemetry.counts_towards_the_arm(record.get("status", ""))
        )

    @property
    def excluded(self) -> tuple[dict, ...]:
        """Cells the API would not serve. They measure nothing and are left out."""
        return tuple(record for record in self.records if record not in self.counted)

    @property
    def arms(self) -> tuple[str, ...]:
        return tuple(sorted({record["arm"] for record in self.records}))

    @property
    def change_requests(self) -> tuple[str, ...]:
        return tuple(sorted({record["change_request"] for record in self.records}))

    @property
    def seeds(self) -> int:
        """The smallest number of seeds any cell was run at."""
        by_cell: dict[tuple[str, str], set[int]] = {}
        for record in self.records:
            key = (record["change_request"], record["arm"])
            by_cell.setdefault(key, set()).add(record["seed"])
        return min((len(seeds) for seeds in by_cell.values()), default=0)

    def for_arm(self, arm: str) -> tuple[dict, ...]:
        return tuple(record for record in self.counted if record["arm"] == arm)

    def for_cell(self, change_request: str, arm: str) -> tuple[dict, ...]:
        return tuple(
            record
            for record in self.counted
            if record["change_request"] == change_request and record["arm"] == arm
        )

    @property
    def is_pilot(self) -> bool:
        """Whether this run set may be called anything but a pilot.

        Decided by the data rather than by a flag, so that nothing is labelled
        as results by forgetting to say it is not.
        """
        return (
            self.seeds < MANUSCRIPT_SEEDS or len(self.change_requests) < MANUSCRIPT_CHANGE_REQUESTS
        )

    @property
    def label(self) -> str:
        return PILOT_LABEL if self.is_pilot else FULL_LABEL

    def why_pilot(self) -> list[str]:
        """What this run set would need before its numbers could be reported."""
        reasons = []
        if self.seeds < MANUSCRIPT_SEEDS:
            reasons.append(
                f"{self.seeds} independent repetition(s) per cell; the discipline is "
                f"{MANUSCRIPT_SEEDS} or more"
            )
        if len(self.change_requests) < MANUSCRIPT_CHANGE_REQUESTS:
            reasons.append(
                f"{len(self.change_requests)} change request(s); the set is "
                f"{MANUSCRIPT_CHANGE_REQUESTS} or more"
            )
        return reasons


def load(runs_directory: Path | None = None) -> RunSet:
    """Every cell with a terminal record, newest attempt per cell."""
    directory = runs_directory or RUNS_DIR
    records = telemetry.completed_cells(directory).values()
    return RunSet(
        records=tuple(sorted(records, key=lambda r: (r["change_request"], r["arm"], r["seed"])))
    )


def load_index(runs_directory: Path | None = None) -> list[dict]:
    """Every attempt ever recorded, including ones later superseded."""
    directory = runs_directory or RUNS_DIR
    return telemetry.read_index(directory / telemetry.INDEX_NAME)


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path
