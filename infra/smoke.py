#!/usr/bin/env python3
"""Prove the executor plumbing with one trivial run.

Puts a small, unambiguous task to the pinned executor in a real workspace and
reports what came back: the credential resolved, the process ran under the
budgets, the stream was captured, the tokens were parsed and costed, and the
workspace change was detected.

This validates the harness, nothing else. Its numbers are apparatus checks and
belong in no result, table or figure.

    python infra/smoke.py                 in a scratch workspace
    python infra/smoke.py --on-target     in a worktree of the pinned application
    python infra/smoke.py --debug-model   on the cheaper model, for harness work
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.common import executor, locks, telemetry  # noqa: E402
from pipelines.common import workspace as workspace_module  # noqa: E402

MARKER = "harness-plumbing-ok"
TASK = (
    "Create a file named smoke.txt in the current directory whose only content is "
    f"the single line {MARKER}. Then reply with the word done and nothing else."
)


def prepare(cell: Path, on_target: bool) -> Path:
    if on_target:
        return workspace_module.create(cell)
    workspace = cell / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--on-target", action="store_true", help="use a workspace of the pin")
    parser.add_argument("--debug-model", action="store_true", help="use the debug model")
    parser.add_argument("--keep", action="store_true", help="leave the run directory in place")
    parser.add_argument("--runs", type=Path, default=locks.REPO_ROOT / "runs")
    arguments = parser.parse_args(argv)

    settings = locks.executor()
    model = settings["model"]["debug"]["id"] if arguments.debug_model else settings["model"]["id"]
    budget = executor.Budget(max_turns=8, wall_clock_seconds=180, max_cost_usd=0.25)
    cell = arguments.runs / "smoke"
    if cell.exists():
        shutil.rmtree(cell, ignore_errors=True)

    workspace = prepare(cell, arguments.on_target)
    print(f"workspace   {workspace}")
    print(
        f"budget      {budget.max_turns} turns, {budget.wall_clock_seconds:g}s, "
        f"${budget.max_cost_usd:g}"
    )

    try:
        execution = executor.execute(TASK, workspace, cell, model=model, budget=budget)
    except executor.ExecutorUnavailable as error:
        print(f"\nthe executor is not usable here: {error}")
        return 2

    written = workspace / "smoke.txt"
    changes = workspace_module.changes(workspace) if arguments.on_target else None
    if execution.per_model_usage:
        cost, by_model = telemetry.cost_by_model(execution.per_model_usage)
    else:
        cost, by_model = telemetry.compute_cost(execution.usage, model), {}

    print()
    print(
        f"status      {execution.status}"
        + (f" ({execution.error_class})" if execution.error_class else "")
    )
    print(f"turns       {execution.turns}")
    print(f"tools       {execution.tool_calls['total']}  {execution.tool_calls['by_name']}")
    print(
        f"tokens      in {execution.usage.input_tokens}  out {execution.usage.output_tokens}"
        f"  reasoning {execution.usage.reasoning_tokens}"
        f"  cache read {execution.usage.cache_read_input_tokens}"
        f"  api calls {execution.usage.api_calls}"
    )
    print(
        f"wall time   {execution.wall_time_seconds:.1f}s  (api {execution.api_time_seconds:.1f}s)"
    )
    print(
        f"cost        ${cost:.6f} computed from the price table"
        f"  (executor reported ${execution.executor_reported_cost_usd or 0:.6f})"
    )
    for billed, amount in sorted(by_model.items()):
        print(f"              ${amount:.6f}  {billed}")
    if changes is not None:
        print(
            f"changes     {changes.files_changed} file(s), "
            f"+{changes.insertions}/-{changes.deletions}"
        )
    print(f"transcript  {(cell / 'transcript.jsonl').stat().st_size} bytes")

    variable, secret = executor.credential()
    artifacts = [cell / "transcript.jsonl", cell / "stderr.txt"]
    leaked = [path.name for path in artifacts if path.exists() and secret in path.read_text()]
    print(
        f"credential  {variable} resolved; "
        + (f"LEAKED in {', '.join(leaked)}" if leaked else "absent from every artifact")
    )

    produced = written.exists() and MARKER in written.read_text()
    print(
        f"task        {'the file was written as asked' if produced else 'the file was NOT written'}"
    )

    events = sum(1 for _ in (cell / "transcript.jsonl").open())
    print(f"events      {events} captured")

    passed = execution.status == "completed" and produced and not leaked
    print("\nsmoke test passed" if passed else "\nsmoke test failed")
    if arguments.on_target:
        workspace_module.remove(workspace)
    if not arguments.keep:
        shutil.rmtree(cell / "home", ignore_errors=True)
    else:
        print(f"\nrun directory kept at {cell}")
    print(json.dumps({"status": execution.status, "cost_usd": round(cost, 6)}, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
