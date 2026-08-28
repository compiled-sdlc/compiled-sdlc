"""Verification: what the harness does after the agent has stopped.

Two things decide whether a run counted. The `must` invariants are boundaries
the change was not allowed to cross, and they are evaluated against the
workspace and the pin. The acceptance checks are the hidden tests: they are
placed in the workspace only now, run, and removed again.

A run is a verified success only if every acceptance check passes and no `must`
invariant is violated. Anything the harness could not evaluate — no toolchain,
a build that would not run — is `error`, never `pass`: an unrun check is not
evidence, and treating it as one would put an unearned success in the numbers.
"""

import re
import subprocess
import time
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from pipelines.common import locks, toolchain
from pipelines.common import workspace as workspace_module
from pipelines.common.changerequests import AcceptanceCheck, ChangeRequest, Invariant

PASS, FAIL, ERROR, NOT_RUN = "pass", "fail", "error", "not_run"

DEPENDENCY = re.compile(
    r"<dependency>\s*(?:<!--.*?-->\s*)*?<groupId>(?P<group>[^<]+)</groupId>\s*"
    r"<artifactId>(?P<artifact>[^<]+)</artifactId>",
    re.DOTALL,
)


class ToolchainUnavailable(RuntimeError):
    """The target application's build cannot run on this machine."""


def toolchain_problem() -> str | None:
    """Why the application's tests cannot be run here, if they cannot.

    The JDK is the one configured in the untracked dotenv, never whatever is
    first on the path: a second, older Java would silently change what the
    experiment compiled against.
    """
    try:
        toolchain.check()
    except toolchain.ToolchainUnavailable as error:
        return str(error)
    return None


def outcome(identifier: str, kind: str, status: str, detail: str = "") -> dict:
    return {"id": identifier, "kind": kind, "status": status, "detail": detail}


# When several modules are verified, the whole is only as good as its worst part.
SEVERITY = {PASS: 0, NOT_RUN: 1, ERROR: 2, FAIL: 3}


def worst(statuses) -> str:
    """The least good of several statuses, or not-run when there are none."""
    collected = list(statuses)
    return max(collected, key=lambda status: SEVERITY.get(status, 2)) if collected else NOT_RUN


# --- invariants ------------------------------------------------------------


def dependencies(pom: str) -> set[str]:
    """The dependency coordinates a module declares."""
    return {
        f"{match.group('group').strip()}:{match.group('artifact').strip()}"
        for match in DEPENDENCY.finditer(pom)
    }


def check_invariant(
    invariant: Invariant,
    request: ChangeRequest,
    workspace: Path,
    changes: workspace_module.Changes,
    *,
    module_tests: str = NOT_RUN,
    checkout: Path | None = None,
    commit: str | None = None,
) -> dict:
    """Evaluate one boundary against the workspace and the pin."""
    kind = invariant.kind

    if kind == "module_tests_pass":
        return outcome(invariant.id, kind, module_tests, "the module's own test suite")

    if kind == "no_new_dependency":
        # Every module the request names, so a cross-service change cannot pay for
        # itself with a dependency on the far side of the boundary.
        added: set[str] = set()
        for module_path in request.module_paths:
            pom = f"{module_path}/pom.xml"
            before = workspace_module.content_at_pin(pom, checkout, commit)
            current = (workspace / pom).read_text() if (workspace / pom).exists() else None
            if before is None or current is None:
                return outcome(invariant.id, kind, ERROR, f"could not read {pom}")
            added |= {
                f"{module_path}: {added_one}"
                for added_one in dependencies(current) - dependencies(before)
            }
        if added:
            return outcome(invariant.id, kind, FAIL, "added " + ", ".join(sorted(added)))
        return outcome(invariant.id, kind, PASS)

    if kind == "file_unchanged":
        for path in invariant.paths:
            before = workspace_module.content_at_pin(path, checkout, commit)
            target = workspace / path
            current = target.read_text() if target.exists() else None
            if before != current:
                return outcome(invariant.id, kind, FAIL, f"{path} is not as the pin had it")
        return outcome(invariant.id, kind, PASS)

    if kind == "paths_untouched":
        touched = sorted(
            {path for prefix in invariant.prefixes for path in changes.touched(prefix)}
        )
        if touched:
            return outcome(invariant.id, kind, FAIL, "changed " + ", ".join(touched))
        return outcome(invariant.id, kind, PASS)

    if kind in {"text_present", "text_absent"}:
        pattern = re.compile(invariant.pattern)
        for path in invariant.paths:
            target = workspace / path
            if not target.exists():
                detail = f"{path} is gone"
                return outcome(invariant.id, kind, FAIL if kind == "text_present" else PASS, detail)
            found = bool(pattern.search(target.read_text()))
            if kind == "text_present" and not found:
                return outcome(invariant.id, kind, FAIL, f"{path} no longer matches the pattern")
            if kind == "text_absent" and found:
                return outcome(invariant.id, kind, FAIL, f"{path} matches the pattern")
        return outcome(invariant.id, kind, PASS)

    return outcome(invariant.id, kind, ERROR, f"unknown invariant kind {kind!r}")


# --- hidden acceptance checks ----------------------------------------------


def place(checks: tuple[AcceptanceCheck, ...], workspace: Path) -> list[Path]:
    """Put the hidden tests in the workspace. Only ever called after the run."""
    placed = []
    for check in checks:
        destination = workspace / check.destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(check.source.read_text())
        placed.append(destination)
    return placed


def withdraw(placed: list[Path]) -> None:
    """Take them out again, so the workspace on disk is what the agent left."""
    for path in placed:
        path.unlink(missing_ok=True)


def test_command(module_path: str, test_classes: list[str]) -> list[str]:
    """The build's own test command, from the pin.

    With no classes named, the module's whole suite runs; naming them selects
    just those. The two are different commands in the pin, not one command with
    an empty argument.
    """
    settings = locks.target()["test"]
    if test_classes:
        rendered = settings["module_test_command"].format(
            module=module_path, tests=",".join(test_classes)
        )
    else:
        rendered = settings["module_suite_command"].format(module=module_path)
    return rendered.split()


def parse_reports(module_directory: Path) -> dict:
    """Test counts from the build's report files, when it wrote any."""
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    reports = module_directory / "target" / "surefire-reports"
    for report in sorted(reports.glob("TEST-*.xml")) if reports.exists() else []:
        try:
            root = ElementTree.parse(report).getroot()
        except ElementTree.ParseError:
            continue
        for key in totals:
            totals[key] += int(root.get(key, 0) or 0)
    return totals


def run_module_tests(
    workspace: Path, module_path: str, test_classes: list[str], timeout: float
) -> dict:
    """Run part of the application's test suite in a workspace."""
    problem = toolchain_problem()
    if problem:
        return {"status": ERROR, "detail": problem, "command": "", "reports": {}}
    command = test_command(module_path, test_classes)
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=toolchain.environment(),
        )
    except subprocess.TimeoutExpired:
        return {
            "status": ERROR,
            "detail": f"the build did not finish within {timeout:g}s",
            "command": " ".join(command),
            "duration_seconds": round(time.monotonic() - started, 2),
            "reports": {},
        }
    except FileNotFoundError as error:
        return {"status": ERROR, "detail": str(error), "command": " ".join(command), "reports": {}}
    return {
        "status": PASS if completed.returncode == 0 else FAIL,
        "detail": "" if completed.returncode == 0 else completed.stdout[-2000:],
        "command": " ".join(command),
        "duration_seconds": round(time.monotonic() - started, 2),
        "reports": parse_reports(workspace / module_path),
    }


# --- the whole verification ------------------------------------------------


def place_for(request: ChangeRequest, module: str, workspace: Path) -> list[Path]:
    return place(request.checks_for(module), workspace)


def run_stack() -> tuple[bool, str]:
    """Bring the local stack up for a change request that needs it."""
    settings = locks.target()["build"]
    started = subprocess.run(
        settings["up_command"].split(),
        cwd=locks.REPO_ROOT,
        capture_output=True,
        text=True,
        env=toolchain.environment(),
    )
    return started.returncode == 0, started.stdout[-1000:] + started.stderr[-1000:]


def stop_stack() -> None:
    subprocess.run(
        locks.target()["build"]["down_command"].split(),
        cwd=locks.REPO_ROOT,
        capture_output=True,
        check=False,
    )


def verify(
    request: ChangeRequest,
    workspace: Path,
    *,
    timeout: float = 1800,
    checkout: Path | None = None,
    commit: str | None = None,
    runner=run_module_tests,
    stack: bool | None = None,
) -> dict:
    """Everything the harness decides after the agent has finished.

    A change request that names more than one module is verified in each of
    them: the module's own suite must still pass, and the hidden checks that
    declare that module are placed there, run, and withdrawn.
    """
    changes = workspace_module.changes(workspace)
    wants_stack = request.needs_stack if stack is None else stack

    stack_detail = ""
    if wants_stack:
        running, stack_detail = run_stack()
        if not running:
            return {
                "verified_success": False,
                "acceptance": {
                    "status": ERROR,
                    "detail": f"the change request needs the running stack, which did not "
                    f"start: {stack_detail[:400]}",
                    "checks": [
                        {"id": check.id, "test_class": check.test_class}
                        for check in request.acceptance
                    ],
                    "per_module": {},
                },
                "invariants": [
                    outcome(item.id, item.kind, NOT_RUN, "the stack did not start")
                    for item in request.must_invariants
                ],
                "violated": [item.id for item in request.must_invariants],
                "changes": changes.to_dict(),
                "needed_stack": True,
            }

    try:
        suites: dict[str, str] = {}
        if any(item.kind == "module_tests_pass" for item in request.must_invariants):
            for module_path in request.module_paths:
                suites[module_path] = runner(workspace, module_path, [], timeout)["status"]
        module_tests = worst(suites.values()) if suites else NOT_RUN

        per_module: dict[str, dict] = {}
        for module, module_path in zip(request.modules, request.module_paths, strict=True):
            checks = request.checks_for(module)
            if not checks:
                continue
            placed = place(checks, workspace)
            try:
                per_module[module_path] = runner(
                    workspace,
                    module_path,
                    [check.simple_class_name for check in checks],
                    timeout,
                )
            finally:
                withdraw(placed)
    finally:
        if wants_stack:
            stop_stack()

    acceptance_status = worst(result["status"] for result in per_module.values())
    invariants = [
        check_invariant(
            invariant,
            request,
            workspace,
            changes,
            module_tests=module_tests,
            checkout=checkout,
            commit=commit,
        )
        for invariant in request.must_invariants
    ]

    violated = [item["id"] for item in invariants if item["status"] != PASS]
    return {
        "verified_success": acceptance_status == PASS and not violated,
        "acceptance": {
            "status": acceptance_status,
            "detail": " | ".join(
                f"{module}: {result['detail'][:300]}"
                for module, result in per_module.items()
                if result["status"] != PASS
            ),
            "duration_seconds": sum(
                result.get("duration_seconds", 0.0) for result in per_module.values()
            ),
            "per_module": {
                module: {
                    "status": result["status"],
                    "command": result.get("command", ""),
                    "reports": result.get("reports", {}),
                }
                for module, result in per_module.items()
            },
            "module_suites": suites,
            "checks": [
                {"id": check.id, "module": check.module, "test_class": check.test_class}
                for check in request.acceptance
            ],
        },
        "invariants": invariants,
        "violated": violated,
        "changes": changes.to_dict(),
        "needed_stack": wants_stack,
    }
