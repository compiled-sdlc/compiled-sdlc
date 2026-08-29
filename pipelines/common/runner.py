"""The run matrix: every {change request x arm x seed} cell, once.

The matrix is resumable. A cell that already has a terminal record is skipped,
so a run interrupted by an exhausted balance, a rate limit, or a closed laptop
is continued by invoking the runner again with the same arguments. Nothing is
retried silently: a cell that aborted stays aborted with the class of failure
that ended it, and is only re-run if it is explicitly cleared.

An arm decides what artifacts the agent is given for a change request; that is
the whole of the difference between arms. Everything else here — the workspace,
the budgets, the executor, the verification, the record — is identical for all
of them, which is what makes their costs comparable.
"""

import argparse
import hashlib
import importlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pipelines.common import arms as arms_module
from pipelines.common import changerequests, executor, locks, telemetry, verify
from pipelines.common import workspace as workspace_module
from pipelines.common.changerequests import ChangeRequest
from pipelines.common.telemetry import RunRecord

ARMS = ("baseline", "lcir", "lcir_no_ast", "compressed")
RUNS_DIR = locks.REPO_ROOT / "runs"
DEFAULT_SEEDS = 3
CONSECUTIVE_ABORT_LIMIT = 3


class Arm(Protocol):
    """What an arm has to provide. Implemented per arm in pipelines/<arm>/."""

    name: str

    def prepare(self, request: ChangeRequest, workspace: Path) -> dict:
        """Place this arm's artifacts in the workspace. Returns what it placed."""

    def prompt(self, request: ChangeRequest, workspace: Path) -> str:
        """The instruction the agent is given. Built from the brief, never the ground truth."""


def load_arm(name: str) -> Arm:
    """The arm of that name, from its own package."""
    if name not in ARMS:
        raise ValueError(f"unknown arm {name!r}; the experiment has {', '.join(ARMS)}")
    try:
        module = importlib.import_module(f"pipelines.{name}.arm")
    except ModuleNotFoundError as error:
        raise ValueError(f"the {name} arm is not implemented yet ({error})") from error
    return module.Arm()


@dataclass
class Cell:
    """One point in the matrix."""

    request: ChangeRequest
    arm: str
    seed: int

    @property
    def run_id(self) -> str:
        return telemetry.cell_id(self.request.id, self.arm, self.seed)


def matrix(requests: list[ChangeRequest], arms: list[str], seeds: int) -> list[Cell]:
    """Every cell, in a fixed order so a resumed run covers the same ground."""
    return [
        Cell(request, arm, seed)
        for request in requests
        for arm in arms
        for seed in range(1, seeds + 1)
    ]


def pending(cells: list[Cell], runs_directory: Path) -> list[Cell]:
    """The cells with no terminal record under the arm's current prompt template.

    Resumability skips a cell that already ran. What it must not do is skip a
    cell that ran under a *different* prompt: an arm's template is frozen for
    the experiment and revising it spends an allowance, so a record made before
    the revision measures a different condition. Such a cell is pending again,
    and re-running it overwrites the stale record.
    """
    done = telemetry.completed_cells(runs_directory)
    remaining = []
    for cell in cells:
        record = done.get(cell.run_id)
        if record is None:
            remaining.append(cell)
            continue
        recorded = (record.get("request") or {}).get("prompt_template_sha256")
        if recorded != load_arm(cell.arm).template_digest():
            remaining.append(cell)
    return remaining


def run_cell(
    cell: Cell,
    runs_directory: Path,
    *,
    budget: executor.Budget | None = None,
    model: str | None = None,
    keep_workspace: bool = False,
    verify_timeout: float = 1800,
) -> RunRecord:
    """Prepare, run, verify and record one cell."""
    budget = budget or executor.Budget.pinned()
    model = model or locks.executor()["model"]["id"]
    cell_directory = runs_directory / cell.run_id
    cell_directory.mkdir(parents=True, exist_ok=True)

    record = RunRecord(
        run_id=cell.run_id,
        change_request=cell.request.id,
        arm=cell.arm,
        seed=cell.seed,
        status="aborted",
        error_class="setup_failed",
        pricing_captured_on=locks.pricing()["captured_on"],
    )

    try:
        arm = load_arm(cell.arm)
        workspace = workspace_module.create(cell_directory)
        arm.prepare(cell.request, workspace)
        prompt = arm.prompt(cell.request, workspace)
    except (ValueError, workspace_module.WorkspaceError) as error:
        record.error_detail = str(error)
        record.finished_at = telemetry.now()
        record.write(cell_directory, index=runs_directory / telemetry.INDEX_NAME)
        return record

    allowance = arms_module.allowances().get(cell.arm)
    record.request = {
        "model": model,
        "max_turns": budget.max_turns,
        "wall_clock_seconds": budget.wall_clock_seconds,
        "max_cost_usd": budget.max_cost_usd,
        "tools": list(locks.executor()["invocation"]["tools"]),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "prompt_template_sha256": arm.template_digest(),
        "prompt_iterations_used": allowance.iterations_used if allowance else None,
        "prompt_iteration_allowance": allowance.allowance if allowance else None,
    }

    execution = executor.execute(prompt, workspace, cell_directory, model=model, budget=budget)

    record.status = execution.status
    record.error_class = execution.error_class
    record.error_detail = execution.error_detail
    record.usage = execution.usage
    record.turns = execution.turns
    record.tool_calls = execution.tool_calls
    record.retries = execution.retries
    record.permission_denials = execution.permission_denials
    record.wall_time_seconds = execution.wall_time_seconds
    record.api_time_seconds = execution.api_time_seconds
    record.executor_reported_cost_usd = execution.executor_reported_cost_usd
    record.response = execution.response
    if execution.per_model_usage:
        record.cost_usd, record.cost_by_model = telemetry.cost_by_model(execution.per_model_usage)
    else:
        record.cost_usd = round(telemetry.compute_cost(execution.usage, model), 6)
    record.artifacts = {"transcript": "transcript.jsonl", "stderr": "stderr.txt"}

    # An aborted cell is a failure of the apparatus: whatever is in the
    # workspace was not produced under the conditions being measured, so it is
    # not verified and not counted.
    if execution.status != "aborted":
        verification = verify.verify(cell.request, workspace, timeout=verify_timeout)
        record.verification = verification
        record.workspace = {
            "path": str(workspace.relative_to(locks.REPO_ROOT))
            if workspace.is_relative_to(locks.REPO_ROOT)
            else str(workspace),
            "base_commit": locks.target()["target"]["commit"],
            **verification.pop("changes", {}),
        }
        if record.status == "completed" and not verification["verified_success"]:
            record.status = "verification_failed"
        try:
            record.arm_artifacts = arm.finalise(
                cell.request, workspace, cell_directory, dict(verification)
            )
        except Exception as error:  # noqa: BLE001 - recorded, never fatal to the cell
            record.arm_artifacts = {"error": f"{type(error).__name__}: {error}"}

    diff = workspace_module.git("diff", "--cached", cwd=workspace).stdout
    (cell_directory / "diff.patch").write_text(diff)
    record.artifacts["diff"] = "diff.patch"

    if not keep_workspace:
        workspace_module.remove(workspace)
        shutil.rmtree(cell_directory / "home", ignore_errors=True)

    record.finished_at = telemetry.now()
    record.write(cell_directory, index=runs_directory / telemetry.INDEX_NAME)
    return record


def run(
    request: ChangeRequest,
    arm: str,
    seed: int,
    *,
    runs_directory: Path | None = None,
    **options,
) -> RunRecord:
    """Run one change request, on one arm, at one seed, and return its record.

    This is the interface the experiment is defined in terms of. Everything the
    arms share passes through it; the arm decides only how the change request is
    represented.
    """
    return run_cell(Cell(request, arm, seed), runs_directory or RUNS_DIR, **options)


def run_matrix(
    cells: list[Cell],
    runs_directory: Path,
    *,
    abort_limit: int = CONSECUTIVE_ABORT_LIMIT,
    cell_runner=run_cell,
    **cell_options,
) -> list[RunRecord]:
    """Run every pending cell, giving up if the apparatus keeps failing."""
    records: list[RunRecord] = []
    consecutive_aborts = 0
    for cell in cells:
        print(f"running {cell.run_id}", flush=True)
        record = cell_runner(cell, runs_directory, **cell_options)
        records.append(record)
        detail = f" ({record.error_class})" if record.error_class else ""
        print(
            f"  {record.status}{detail}"
            f"  {record.usage.total_tokens} tokens"
            f"  ${record.cost_usd:.4f}"
            f"  {record.wall_time_seconds:.0f}s",
            flush=True,
        )
        if record.status == "aborted":
            consecutive_aborts += 1
            if consecutive_aborts >= abort_limit:
                print(
                    f"\nstopping: {consecutive_aborts} cells in a row aborted "
                    f"({record.error_class}). The remaining cells are still pending and "
                    f"will be picked up when the runner is invoked again."
                )
                break
        else:
            consecutive_aborts = 0
    return records


def summarise(records: list[RunRecord]) -> str:
    """A one-line-per-status tally. Pilot numbers only; never a reported result."""
    if not records:
        return "no cells run"
    by_status: dict[str, int] = {}
    for record in records:
        by_status[record.status] = by_status.get(record.status, 0) + 1
    verified = sum(1 for record in records if record.verified_success)
    cost = sum(record.cost_usd for record in records)
    tokens = sum(record.usage.total_tokens for record in records)
    tally = "  ".join(f"{status}={count}" for status, count in sorted(by_status.items()))
    return f"{len(records)} cells: {tally}\nverified {verified}  {tokens} tokens  ${cost:.4f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the experiment matrix.")
    parser.add_argument("--arm", action="append", choices=ARMS, help="repeatable; default all")
    parser.add_argument("--change-request", action="append", help="repeatable; default all")
    parser.add_argument("--seeds", type=int, default=DEFAULT_SEEDS)
    parser.add_argument("--runs", type=Path, default=RUNS_DIR)
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument("--plan", action="store_true", help="list the pending cells and stop")
    arguments = parser.parse_args(argv)

    requests = changerequests.load_all()
    if arguments.change_request:
        wanted = set(arguments.change_request)
        requests = [request for request in requests if request.id in wanted]
        missing = wanted - {request.id for request in requests}
        if missing:
            print(f"no such change request: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2
    arms = arguments.arm or list(ARMS)

    cells = matrix(requests, arms, arguments.seeds)
    outstanding = pending(cells, arguments.runs)
    print(f"{len(cells)} cells, {len(outstanding)} pending")
    if arguments.plan:
        for cell in outstanding:
            print(f"  {cell.run_id}")
        return 0

    records = run_matrix(outstanding, arguments.runs, keep_workspace=arguments.keep_workspace)
    print()
    print(summarise(records))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
