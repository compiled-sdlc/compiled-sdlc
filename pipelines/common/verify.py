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
        pom = f"{request.module_path}/pom.xml"
        before = workspace_module.content_at_pin(pom, checkout, commit)
        current = (workspace / pom).read_text() if (workspace / pom).exists() else None
        if before is None or current is None:
            return outcome(invariant.id, kind, ERROR, f"could not read {pom}")
        added = dependencies(current) - dependencies(before)
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
    """The build's own test command, from the pin, for these test classes."""
    template = locks.target()["test"]["module_test_command"]
    rendered = template.format(module=module_path, tests=",".join(test_classes))
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


def verify(
    request: ChangeRequest,
    workspace: Path,
    *,
    timeout: float = 1800,
    checkout: Path | None = None,
    commit: str | None = None,
    runner=run_module_tests,
) -> dict:
    """Everything the harness decides after the agent has finished."""
    changes = workspace_module.changes(workspace)
    module_path = request.module_path

    module_tests = NOT_RUN
    if any(item.kind == "module_tests_pass" for item in request.must_invariants):
        outcome_of_suite = runner(workspace, module_path, [], timeout)
        module_tests = outcome_of_suite["status"]

    placed = place(request.acceptance, workspace)
    try:
        acceptance = runner(
            workspace,
            module_path,
            [check.simple_class_name for check in request.acceptance],
            timeout,
        )
    finally:
        withdraw(placed)

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
        "verified_success": acceptance["status"] == PASS and not violated,
        "acceptance": {
            "status": acceptance["status"],
            "detail": acceptance.get("detail", ""),
            "command": acceptance.get("command", ""),
            "duration_seconds": acceptance.get("duration_seconds", 0.0),
            "reports": acceptance.get("reports", {}),
            "checks": [
                {"id": check.id, "test_class": check.test_class} for check in request.acceptance
            ],
        },
        "invariants": invariants,
        "violated": violated,
        "changes": changes.to_dict(),
    }
