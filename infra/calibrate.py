#!/usr/bin/env python3
"""Calibrate the change-request set against the pristine pin.

A hidden acceptance check earns its place only if it is red before the change
and green after it. One that passes on the unmodified application cannot tell a
successful run from an agent that did nothing, and would credit every arm with
a success it did not earn. A `must` invariant has to hold the other way round:
it must pass on the pristine pin, or every run starts already in violation.

So, for each change request, against a fresh workspace at the pin and with no
change applied:

  - the module's own test suite must pass;
  - every `must` invariant must pass;
  - every hidden acceptance check must fail, and fail by assertion rather than
    by failing to compile — a check that does not build is not a discriminator.

The result is written to bench/calibration.json.

    python infra/calibrate.py [--change-request CR-101 ...] [--output PATH]
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.common import changerequests, locks, verify  # noqa: E402
from pipelines.common import workspace as workspace_module  # noqa: E402

OUTPUT = locks.REPO_ROOT / "bench" / "calibration.json"
COMPILATION_MARKERS = ("COMPILATION ERROR", "Compilation failure", "cannot find symbol")


def compiled(detail: str) -> bool:
    """Whether a failing run got as far as running the tests."""
    return not any(marker in detail for marker in COMPILATION_MARKERS)


def calibrate(request: changerequests.ChangeRequest, cell: Path, timeout: float) -> dict:
    """Run one change request's ground truth against the unmodified pin.

    A request may name more than one module. Each named module's own suite has
    to be green, and each module's own hidden checks have to be red, so a
    cross-service change is calibrated on both sides of the boundary.
    """
    workspace = workspace_module.create(cell)
    findings: list[str] = []
    started = time.monotonic()
    suites: dict[str, str] = {}
    per_module: dict[str, dict] = {}
    try:
        for module_path in request.module_paths:
            suite = verify.run_module_tests(workspace, module_path, [], timeout)
            suites[module_path] = suite["status"]
            if suite["status"] != verify.PASS:
                findings.append(
                    f"{module_path}: the module's own suite is {suite['status']} "
                    f"on the pristine pin"
                )

        changes = workspace_module.changes(workspace)
        module_tests = verify.worst(suites.values())
        invariants = [
            verify.check_invariant(item, request, workspace, changes, module_tests=module_tests)
            for item in request.must_invariants
        ]
        for item in invariants:
            if item["status"] != verify.PASS:
                findings.append(f"{item['id']} is {item['status']} before any change")

        for module, module_path in zip(request.modules, request.module_paths, strict=True):
            checks = request.checks_for(module)
            if not checks:
                continue
            placed = verify.place(checks, workspace)
            try:
                outcome = verify.run_module_tests(
                    workspace,
                    module_path,
                    [check.simple_class_name for check in checks],
                    timeout,
                )
            finally:
                verify.withdraw(placed)
            per_module[module_path] = outcome

            if outcome["status"] == verify.PASS:
                findings.append(
                    f"{module_path}: the hidden checks pass on the unmodified pin, so "
                    f"they cannot discriminate a real change from no change at all"
                )
            elif outcome["status"] == verify.ERROR:
                findings.append(
                    f"{module_path}: the hidden checks could not be run: {outcome['detail'][:200]}"
                )
            elif not compiled(outcome["detail"]):
                findings.append(
                    f"{module_path}: the hidden checks do not compile against the pin, "
                    f"so they are red for the wrong reason"
                )
    finally:
        workspace_module.remove(workspace)

    return {
        "change_request": request.id,
        "modules": list(request.module_paths),
        "needs_stack": request.needs_stack,
        "module_suite": verify.worst(suites.values()),
        "module_suites": suites,
        "invariants": [
            {"id": item["id"], "kind": item["kind"], "status": item["status"]}
            for item in invariants
        ],
        "acceptance": {
            "status": verify.worst(outcome["status"] for outcome in per_module.values()),
            "checks": [check.id for check in request.acceptance],
            "compiled": all(compiled(outcome.get("detail", "")) for outcome in per_module.values()),
            "per_module": {
                module_path: {
                    "status": outcome["status"],
                    "reports": outcome.get("reports", {}),
                    "compiled": compiled(outcome.get("detail", "")),
                }
                for module_path, outcome in per_module.items()
            },
        },
        "calibrated": not findings,
        "findings": findings,
        "duration_seconds": round(time.monotonic() - started, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--change-request", action="append", help="repeatable; default all")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--runs", type=Path, default=locks.REPO_ROOT / "runs" / "calibration")
    arguments = parser.parse_args(argv)

    problem = verify.toolchain_problem()
    if problem:
        print(f"cannot calibrate: {problem}", file=sys.stderr)
        return 2

    requests = changerequests.load_all()
    if arguments.change_request:
        wanted = set(arguments.change_request)
        requests = [request for request in requests if request.id in wanted]

    results = []
    for request in requests:
        print(f"calibrating {request.id} ({', '.join(request.module_paths)})", flush=True)
        result = calibrate(request, arguments.runs / request.id, arguments.timeout)
        results.append(result)
        mark = "ok  " if result["calibrated"] else "FAIL"
        held = all(item["status"] == "pass" for item in result["invariants"])
        print(
            f"  {mark} suite={result['module_suite']}"
            f"  invariants={'all pass' if held else 'NOT all pass'}"
            f"  hidden checks={result['acceptance']['status']}"
            f"  ({result['duration_seconds']}s)"
        )
        for finding in result["findings"]:
            print(f"       {finding}")

    # Calibrating a subset must not throw away the rest of the record. Entries
    # for change requests that were not re-run are carried forward, but only
    # when they were taken against the same pin — evidence from another commit
    # describes another application.
    carried: list[dict] = []
    if arguments.output.exists():
        try:
            existing = json.loads(arguments.output.read_text())
        except json.JSONDecodeError:
            existing = {}
        if existing.get("commit") == locks.target()["target"]["commit"]:
            rerun = {result["change_request"] for result in results}
            carried = [
                entry
                for entry in existing.get("change_requests", [])
                if entry["change_request"] not in rerun
            ]
    results = sorted(results + carried, key=lambda entry: entry["change_request"])

    record = {
        "schema_version": 2,
        "calibrated_on": time.strftime("%Y-%m-%d"),
        "commit": locks.target()["target"]["commit"],
        "rule": (
            "every hidden acceptance check must fail on the unmodified pin and every "
            "must-invariant must pass, or the check cannot discriminate"
        ),
        "change_requests": results,
    }
    arguments.output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    calibrated = sum(1 for result in results if result["calibrated"])
    if carried:
        print(f"carried forward {len(carried)} entry(ies) taken against the same pin")
    output = arguments.output.resolve()
    shown = (
        output.relative_to(locks.REPO_ROOT) if output.is_relative_to(locks.REPO_ROOT) else output
    )
    print(f"\n{calibrated}/{len(results)} calibrated; recorded in {shown}")
    return 0 if calibrated == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
