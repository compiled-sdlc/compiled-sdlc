"""Tests for the workspace and for what the harness decides after a run.

The application's own build needs a toolchain this machine may not have, so the
build is stood in for: a fake runner returns the statuses a real build would,
and everything else — the workspace, the invariants, the placement and
withdrawal of the hidden tests, the success rule — is exercised for real.
"""

import subprocess
from pathlib import Path

import pytest

from pipelines.common import changerequests as cr
from pipelines.common import locks, verify
from pipelines.common import workspace as workspace_module

REPO = Path(__file__).resolve().parents[1]
MODULE = "spring-petclinic-customers-service"

POM = """<project>
  <dependencies>
    <dependency><groupId>org.springframework.boot</groupId><artifactId>starter</artifactId></dependency>
    <dependency><groupId>org.hsqldb</groupId><artifactId>hsqldb</artifactId></dependency>
  </dependencies>
</project>
"""


@pytest.fixture
def pinned_application(tmp_path) -> Path:
    """A stand-in for the target application: a git repository with one commit."""
    checkout = tmp_path / "target"
    (checkout / MODULE / "src" / "main").mkdir(parents=True)
    (checkout / MODULE / "pom.xml").write_text(POM)
    (checkout / MODULE / "src" / "main" / "Resource.java").write_text(
        "class Resource { HttpStatus.NO_CONTENT; }\n"
    )
    (checkout / "spring-petclinic-visits-service").mkdir()
    (checkout / "spring-petclinic-visits-service" / "pom.xml").write_text(POM)

    def run(*args):
        subprocess.run(["git", *args], cwd=checkout, check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    run("config", "user.name", "Test")
    run("config", "user.email", "test@example.invalid")
    run("add", "-A")
    run("commit", "-q", "-m", "the pin")
    return checkout


@pytest.fixture
def pinned_commit(pinned_application) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=pinned_application, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def cell(tmp_path, pinned_application, pinned_commit) -> Path:
    return workspace_module.create(
        tmp_path / "cell", checkout=pinned_application, commit=pinned_commit
    )


def a_request(**overrides) -> cr.ChangeRequest:
    request = cr.load(cr.CHANGE_REQUEST_DIR / "CR-101.yaml")
    return cr.ChangeRequest(**{**request.__dict__, **overrides})


def an_invariant(**overrides) -> cr.Invariant:
    defaults = {"id": "invariant:x", "kind": "no_new_dependency", "statement": "s"}
    return cr.Invariant(**{**defaults, **overrides})


def evaluate(invariant, workspace, checkout, commit=None, request=None):
    return verify.check_invariant(
        invariant,
        request or a_request(),
        workspace,
        workspace_module.changes(workspace),
        checkout=checkout,
        commit=commit,
    )


# --- the workspace ---------------------------------------------------------


def test_a_workspace_is_a_fresh_checkout_of_the_pin(cell, pinned_commit):
    assert (cell / MODULE / "pom.xml").read_text() == POM
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=cell, capture_output=True, text=True
    ).stdout.strip()
    assert head == pinned_commit


def test_a_workspace_reports_what_the_run_changed(cell):
    (cell / MODULE / "src" / "main" / "Resource.java").write_text("class Resource { }\n")
    (cell / MODULE / "src" / "main" / "New.java").write_text("class New { }\n")
    changes = workspace_module.changes(cell)
    assert changes.files_changed == 2
    assert changes.insertions >= 2
    assert changes.touched("spring-petclinic-visits-service") == []
    assert changes.touched(MODULE) == sorted(changes.changed_paths)


def test_a_workspace_without_a_target_checkout_is_an_error(tmp_path):
    with pytest.raises(workspace_module.WorkspaceError, match="no target checkout"):
        workspace_module.create(tmp_path / "cell", checkout=tmp_path / "absent", commit="HEAD")


def test_a_workspace_can_be_discarded(cell, pinned_application, pinned_commit):
    workspace_module.remove(cell, checkout=pinned_application)
    assert not cell.exists()


def test_the_pin_can_be_read_back_after_the_workspace_changed(
    cell, pinned_application, pinned_commit
):
    target = cell / MODULE / "pom.xml"
    target.write_text("<project/>")
    assert (
        workspace_module.content_at_pin(f"{MODULE}/pom.xml", pinned_application, pinned_commit)
        == POM
    )


# --- invariants ------------------------------------------------------------


def test_an_added_dependency_violates_the_dependency_invariant(
    cell, pinned_application, pinned_commit
):
    pom = cell / MODULE / "pom.xml"
    pom.write_text(
        POM.replace(
            "</dependencies>",
            "<dependency><groupId>com.example</groupId>"
            "<artifactId>rate-limiter</artifactId></dependency></dependencies>",
        )
    )
    result = evaluate(an_invariant(), cell, pinned_application, pinned_commit)
    assert result["status"] == verify.FAIL
    assert "com.example:rate-limiter" in result["detail"]


def test_removing_a_dependency_does_not_violate_it(cell, pinned_application, pinned_commit):
    pom = cell / MODULE / "pom.xml"
    pom.write_text(
        POM.replace(
            "<dependency><groupId>org.hsqldb</groupId><artifactId>hsqldb</artifactId></dependency>",
            "",
        )
    )
    assert (
        evaluate(an_invariant(), cell, pinned_application, pinned_commit)["status"] == verify.PASS
    )


def test_an_untouched_file_satisfies_the_unchanged_invariant(
    cell, pinned_application, pinned_commit
):
    invariant = an_invariant(kind="file_unchanged", paths=(f"{MODULE}/pom.xml",))
    assert evaluate(invariant, cell, pinned_application, pinned_commit)["status"] == verify.PASS


def test_an_edited_file_violates_the_unchanged_invariant(cell, pinned_application, pinned_commit):
    (cell / MODULE / "pom.xml").write_text("<project/>")
    invariant = an_invariant(kind="file_unchanged", paths=(f"{MODULE}/pom.xml",))
    result = evaluate(invariant, cell, pinned_application, pinned_commit)
    assert result["status"] == verify.FAIL
    assert "pom.xml" in result["detail"]


def test_a_deleted_file_violates_the_unchanged_invariant(cell, pinned_application, pinned_commit):
    (cell / MODULE / "pom.xml").unlink()
    invariant = an_invariant(kind="file_unchanged", paths=(f"{MODULE}/pom.xml",))
    assert evaluate(invariant, cell, pinned_application, pinned_commit)["status"] == verify.FAIL


def test_spreading_into_another_service_violates_the_untouched_invariant(
    cell, pinned_application, pinned_commit
):
    (cell / "spring-petclinic-visits-service" / "pom.xml").write_text("<project/>")
    invariant = an_invariant(kind="paths_untouched", prefixes=("spring-petclinic-visits-service",))
    result = evaluate(invariant, cell, pinned_application, pinned_commit)
    assert result["status"] == verify.FAIL
    assert "spring-petclinic-visits-service/pom.xml" in result["detail"]


def test_staying_inside_the_module_satisfies_the_untouched_invariant(
    cell, pinned_application, pinned_commit
):
    (cell / MODULE / "src" / "main" / "Resource.java").write_text("class Resource { }\n")
    invariant = an_invariant(kind="paths_untouched", prefixes=("spring-petclinic-visits-service",))
    assert evaluate(invariant, cell, pinned_application, pinned_commit)["status"] == verify.PASS


def test_a_removed_marker_violates_the_text_present_invariant(
    cell, pinned_application, pinned_commit
):
    path = f"{MODULE}/src/main/Resource.java"
    invariant = an_invariant(kind="text_present", paths=(path,), pattern=r"HttpStatus\.NO_CONTENT")
    assert evaluate(invariant, cell, pinned_application, pinned_commit)["status"] == verify.PASS
    (cell / path).write_text("class Resource { HttpStatus.OK; }\n")
    assert evaluate(invariant, cell, pinned_application, pinned_commit)["status"] == verify.FAIL


def test_an_introduced_string_violates_the_text_absent_invariant(
    cell, pinned_application, pinned_commit
):
    path = f"{MODULE}/src/main/Resource.java"
    invariant = an_invariant(kind="text_absent", paths=(path,), pattern=r"TODO")
    assert evaluate(invariant, cell, pinned_application, pinned_commit)["status"] == verify.PASS
    (cell / path).write_text("class Resource { /* TODO */ }\n")
    assert evaluate(invariant, cell, pinned_application, pinned_commit)["status"] == verify.FAIL


def test_an_unknown_invariant_kind_is_an_error_not_a_pass(cell, pinned_application, pinned_commit):
    result = evaluate(
        an_invariant(kind="wishful_thinking"), cell, pinned_application, pinned_commit
    )
    assert result["status"] == verify.ERROR


def test_the_dependency_reader_finds_the_real_modules_dependencies():
    pom = (locks.target_checkout() / MODULE / "pom.xml").read_text()
    found = verify.dependencies(pom)
    assert "org.hsqldb:hsqldb" in found
    assert len(found) > 5


# --- hidden checks ---------------------------------------------------------


def test_the_hidden_tests_are_placed_only_to_be_run_and_then_withdrawn(cell):
    request = cr.load(cr.CHANGE_REQUEST_DIR / "CR-101.yaml")
    check = request.acceptance[0]
    assert not (cell / check.destination).exists(), "not in the workspace before the run"
    placed = verify.place(request.acceptance, cell)
    assert (cell / check.destination).read_text() == check.source.read_text()
    verify.withdraw(placed)
    assert not (cell / check.destination).exists(), "and not left behind afterwards"


def test_the_test_command_comes_from_the_pin():
    command = verify.test_command(MODULE, ["OneTest", "TwoTest"])
    assert command[0] == "./mvnw"
    assert "-pl" in command and MODULE in command
    assert "-Dtest=OneTest,TwoTest" in command


def test_naming_no_classes_runs_the_whole_module_suite():
    command = verify.test_command(MODULE, [])
    assert not any(part.startswith("-Dtest") for part in command), "not an empty selection"
    assert command[-1] == "test"


# --- the success rule ------------------------------------------------------


def fake_runner(status_by_call: list[str]):
    calls = iter(status_by_call)

    def runner(workspace, module_path, test_classes, timeout):
        return {"status": next(calls), "detail": "", "command": "fake", "reports": {}}

    return runner


def test_a_run_succeeds_only_when_the_hidden_checks_pass_and_no_boundary_is_crossed(
    cell, pinned_application, pinned_commit
):
    request = a_request(
        must_invariants=(an_invariant(kind="module_tests_pass"),),
        acceptance=cr.load(cr.CHANGE_REQUEST_DIR / "CR-101.yaml").acceptance,
    )
    result = verify.verify(
        request,
        cell,
        checkout=pinned_application,
        commit=pinned_commit,
        runner=fake_runner([verify.PASS, verify.PASS]),
    )
    assert result["verified_success"] is True
    assert result["violated"] == []


def test_a_violated_boundary_denies_success_however_green_the_checks(
    cell, pinned_application, pinned_commit
):
    request = a_request(
        must_invariants=(
            an_invariant(kind="paths_untouched", prefixes=("spring-petclinic-visits-service",)),
        ),
        acceptance=cr.load(cr.CHANGE_REQUEST_DIR / "CR-101.yaml").acceptance,
    )
    (cell / "spring-petclinic-visits-service" / "pom.xml").write_text("<project/>")
    result = verify.verify(
        request,
        cell,
        checkout=pinned_application,
        commit=pinned_commit,
        runner=fake_runner([verify.PASS]),
    )
    assert result["acceptance"]["status"] == verify.PASS
    assert result["verified_success"] is False
    assert result["violated"] == ["invariant:x"]


def test_a_failing_hidden_check_denies_success(cell, pinned_application, pinned_commit):
    request = a_request(
        must_invariants=(an_invariant(kind="file_unchanged", paths=(f"{MODULE}/pom.xml",)),),
        acceptance=cr.load(cr.CHANGE_REQUEST_DIR / "CR-101.yaml").acceptance,
    )
    result = verify.verify(
        request,
        cell,
        checkout=pinned_application,
        commit=pinned_commit,
        runner=fake_runner([verify.FAIL]),
    )
    assert result["verified_success"] is False


def test_a_check_that_could_not_be_run_is_never_counted_as_a_pass(
    cell, pinned_application, pinned_commit
):
    request = a_request(
        must_invariants=(an_invariant(kind="module_tests_pass"),),
        acceptance=cr.load(cr.CHANGE_REQUEST_DIR / "CR-101.yaml").acceptance,
    )
    result = verify.verify(
        request,
        cell,
        checkout=pinned_application,
        commit=pinned_commit,
        runner=fake_runner([verify.ERROR, verify.ERROR]),
    )
    assert result["verified_success"] is False
    assert result["invariants"][0]["status"] == verify.ERROR


def test_the_toolchain_is_checked_before_a_build_is_attempted(monkeypatch, tmp_path):
    def unavailable():
        raise verify.toolchain.ToolchainUnavailable("no JAVA_HOME in .env")

    monkeypatch.setattr(verify.toolchain, "check", unavailable)
    result = verify.run_module_tests(tmp_path, MODULE, ["X"], timeout=5)
    assert result["status"] == verify.ERROR
    assert "JAVA_HOME" in result["detail"]


def test_the_configured_toolchain_is_usable_on_this_machine():
    assert verify.toolchain_problem() is None


# --- the arm's artifacts are its input, not the run's output ----------------


def test_the_arms_own_artifacts_are_not_counted_as_changes(cell):
    """An arm that hands over six files has not changed the application six times."""
    artifacts = cell / workspace_module.ARTIFACT_DIRECTORY
    artifacts.mkdir()
    (artifacts / "intent-graph.json").write_text('{"kind": "intent_graph"}\n')
    (artifacts / "constraint-graph.json").write_text('{"kind": "constraint_graph"}\n')
    (cell / MODULE / "src" / "main" / "Resource.java").write_text("class Resource { }\n")

    changes = workspace_module.changes(cell)
    assert changes.files_changed == 1
    assert changes.changed_paths == (f"{MODULE}/src/main/Resource.java",)
    assert len(changes.artifact_paths) == 2
    assert all(
        path.startswith(f"{workspace_module.ARTIFACT_DIRECTORY}/")
        for path in changes.artifact_paths
    )


def test_the_arms_artifacts_do_not_trip_a_scope_invariant(cell, pinned_application, pinned_commit):
    """An arm's own files must not read as the change spreading somewhere it should not."""
    artifacts = cell / workspace_module.ARTIFACT_DIRECTORY
    artifacts.mkdir()
    (artifacts / "intent-graph.json").write_text("{}\n")
    invariant = an_invariant(
        kind="paths_untouched", prefixes=(workspace_module.ARTIFACT_DIRECTORY,)
    )
    assert evaluate(invariant, cell, pinned_application, pinned_commit)["status"] == verify.PASS


def test_insertions_count_only_the_application(cell):
    artifacts = cell / workspace_module.ARTIFACT_DIRECTORY
    artifacts.mkdir()
    (artifacts / "big.json").write_text("\n".join(f'"line {n}"' for n in range(500)) + "\n")
    (cell / MODULE / "src" / "main" / "Resource.java").write_text("class Resource { }\nint x;\n")
    changes = workspace_module.changes(cell)
    assert changes.insertions < 10, "the arm's artifact is not a five-hundred-line change"


def test_a_workspace_is_created_where_the_run_is_not_inside_the_application(
    tmp_path, pinned_application, pinned_commit, monkeypatch
):
    """The worktree is made with the application as the working directory."""
    monkeypatch.chdir(tmp_path)
    workspace = workspace_module.create(
        Path("relative-cell"), checkout=pinned_application, commit=pinned_commit
    )
    assert workspace.is_absolute()
    assert workspace == (tmp_path / "relative-cell" / "workspace").resolve()
    assert (workspace / MODULE / "pom.xml").exists()
    assert not (pinned_application / "relative-cell").exists()
    workspace_module.remove(workspace, checkout=pinned_application)
