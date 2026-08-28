"""Run records: what one {change request x arm x seed} cell produced.

One record per cell, written as `record.json` inside the cell's directory and
appended to `runs/index.jsonl`. The record's presence is also what makes the run
matrix resumable: a cell that already has a terminal record is not run again.

Token fields follow the OpenTelemetry generative-AI convention names where they
have one (`gen_ai.usage.input_tokens` and friends), nested rather than dotted so
the record stays a plain JSON object.

Cost is always recomputed here from recorded tokens and the captured price
table. The executor reports a cost of its own; it is recorded for comparison and
never used as the measurement, because a number in the paper has to be
reproducible from the run records and the prices they were costed at.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pipelines.common import locks

SCHEMA_VERSION = 1
INDEX_NAME = "index.jsonl"
RECORD_NAME = "record.json"

# A cell is finished, whatever the outcome, when its status is one of these.
TERMINAL_STATUSES = frozenset(
    {"completed", "agent_failed", "aborted", "budget_exhausted", "verification_failed"}
)

# What a status means for the measurement, fixed here so every consumer agrees.
#
# A cell that ran out of budget — cost ceiling, turn cap or wall clock — is a
# failure of the agent, not of the apparatus: the budget is a condition of the
# experiment, identical for every arm, and an agent that spends it without
# finishing has failed the change request. It counts against its arm and its
# cost counts in the metric, which is the whole point of dividing cost by
# verified successes.
#
# A cell that ended because the API would not serve it — an exhausted balance, a
# rate limit, an authentication failure — measures nothing about the arm. It is
# excluded from the metrics entirely and can be run again.
AGENT_FAILURE_STATUSES = frozenset({"agent_failed", "verification_failed", "budget_exhausted"})
EXCLUDED_STATUSES = frozenset({"aborted"})

# Why a cell stopped short.
ERROR_CLASSES = frozenset(
    {
        "rate_limit",
        "credit_exhausted",
        "overloaded",
        "auth",
        "network",
        "timeout",
        "turn_budget",
        "cost_budget",
        "wall_clock",
        "executor_crash",
        "setup_failed",
        "unknown",
    }
)

# Failures of the apparatus rather than of the agent. `timeout` here is an API
# call that never answered, not the harness's own wall clock, which is a budget.
ABORT_CLASSES = frozenset(
    {"rate_limit", "credit_exhausted", "overloaded", "auth", "network", "timeout", "setup_failed"}
)

# Budgets the harness or the executor enforces. Reaching one is an agent failure.
BUDGET_CLASSES = frozenset({"turn_budget", "cost_budget", "wall_clock"})


def counts_towards_the_arm(status: str) -> bool:
    """Whether a cell says anything about the arm that ran it."""
    return status not in EXCLUDED_STATUSES


def is_agent_failure(status: str) -> bool:
    """Whether a cell is a failure charged to the arm."""
    return status in AGENT_FAILURE_STATUSES


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def cell_id(change_request: str, arm: str, seed: int) -> str:
    return f"{change_request}__{arm}__seed{seed}"


@dataclass
class Usage:
    """Token counts for one cell, summed over every attempt the executor made."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_5m_tokens: int = 0
    cache_creation_1h_tokens: int = 0
    api_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )


@dataclass
class RunRecord:
    """Everything measured about one cell."""

    run_id: str
    change_request: str
    arm: str
    seed: int
    status: str
    started_at: str = field(default_factory=now)
    finished_at: str = ""
    schema_version: int = SCHEMA_VERSION
    error_class: str | None = None
    error_detail: str = ""
    request: dict = field(default_factory=dict)
    response: dict = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    turns: int = 0
    tool_calls: dict = field(default_factory=lambda: {"total": 0, "by_name": {}})
    retries: int = 0
    permission_denials: int = 0
    wall_time_seconds: float = 0.0
    api_time_seconds: float = 0.0
    cost_usd: float = 0.0
    cost_by_model: dict = field(default_factory=dict)
    executor_reported_cost_usd: float | None = None
    pricing_captured_on: str = ""
    workspace: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    arm_artifacts: dict = field(default_factory=dict)
    artifacts: dict = field(default_factory=dict)

    @property
    def verified_success(self) -> bool:
        """The only kind of success the metric counts."""
        return bool(self.verification.get("verified_success"))

    def to_dict(self) -> dict:
        record = asdict(self)
        record["usage"]["total_tokens"] = self.usage.total_tokens
        record["verified_success"] = self.verified_success
        return record

    def write(self, cell_directory: Path, index: Path | None = None) -> Path:
        """Write the record, and append it to the index if one is given."""
        cell_directory.mkdir(parents=True, exist_ok=True)
        path = cell_directory / RECORD_NAME
        payload = self.to_dict()
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        if index is not None:
            index.parent.mkdir(parents=True, exist_ok=True)
            with index.open("a") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        return path


def price_of(model: str, pricing: dict | None = None) -> dict:
    """The captured prices for one model."""
    table = (pricing or locks.pricing())["models"]
    if model not in table:
        known = ", ".join(sorted(table))
        raise KeyError(f"no captured price for {model!r}; the table holds {known}")
    return table[model]


def compute_cost(usage: Usage, model: str, pricing: dict | None = None) -> float:
    """Cost of one cell, from its recorded tokens and the captured prices.

    Reasoning tokens are already inside the output count and are not priced
    again. Cache creation is split by lifetime because the two are priced
    differently; whatever the executor did not attribute to a lifetime is
    charged at the shorter one.
    """
    rates = price_of(model, pricing)
    attributed = usage.cache_creation_5m_tokens + usage.cache_creation_1h_tokens
    unattributed_creation = max(usage.cache_creation_input_tokens - attributed, 0)
    micros = (
        usage.input_tokens * rates["input"]
        + usage.output_tokens * rates["output"]
        + (usage.cache_creation_5m_tokens + unattributed_creation) * rates["cache_write_5m"]
        + usage.cache_creation_1h_tokens * rates["cache_write_1h"]
        + usage.cache_read_input_tokens * rates["cache_read"]
    )
    return micros / 1_000_000


def cost_by_model(per_model: dict[str, Usage], pricing: dict | None = None) -> tuple[float, dict]:
    """Cost of a cell whose tokens were spent on more than one model.

    The executor bills a smaller model for some of its own internal work, so a
    cell's tokens are not all at the pinned model's prices. Each model's tokens
    are costed at its own captured prices and the results are added; costing the
    total at one model's prices overstates the bill.
    """
    breakdown = {
        model: round(compute_cost(usage, model, pricing), 6)
        for model, usage in sorted(per_model.items())
    }
    return round(sum(breakdown.values()), 6), breakdown


def read_index(index: Path) -> list[dict]:
    """Every record in an index file, oldest first."""
    if not index.exists():
        return []
    return [json.loads(line) for line in index.read_text().splitlines() if line.strip()]


def completed_cells(runs_directory: Path) -> dict[str, dict]:
    """Cells that already have a terminal record, keyed by run id.

    Reads the per-cell records rather than the index: the index is append-only
    and may hold an earlier attempt at a cell that was later re-run.
    """
    found: dict[str, dict] = {}
    if not runs_directory.exists():
        return found
    for path in sorted(runs_directory.glob(f"*/{RECORD_NAME}")):
        try:
            record = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if record.get("status") in TERMINAL_STATUSES and record.get("run_id"):
            found[record["run_id"]] = record
    return found
