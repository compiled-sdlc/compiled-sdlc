"""Tests for the four protocols.

The experimental claim rests on one property: the arms differ in how a change
request is represented and in nothing else. Most of what is tested here is that
property, stated four ways.
"""

import json
from pathlib import Path

import pytest

from pipelines.common import arms as arms_module
from pipelines.common import changerequests as cr
from pipelines.common.runner import ARMS, load_arm

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def request_under_test() -> cr.ChangeRequest:
    return cr.load_all()[0]


@pytest.fixture(scope="module")
def prompts(request_under_test, tmp_path_factory) -> dict[str, str]:
    rendered = {}
    for name in ARMS:
        workspace = tmp_path_factory.mktemp(name)
        arm = load_arm(name)
        arm.prepare(request_under_test, workspace)
        rendered[name] = arm.prompt(request_under_test, workspace)
    return rendered


# --- the four protocols exist and are distinct ----------------------------------


def test_every_arm_is_implemented():
    for name in ARMS:
        assert load_arm(name).name == name


def test_every_arm_renders_a_prompt(prompts):
    for name, prompt in prompts.items():
        assert prompt.strip(), name
        assert len(prompt) > 200, name


def test_the_arms_are_actually_different(prompts):
    assert len(set(prompts.values())) == len(ARMS)


# --- what must be identical ------------------------------------------------


def test_every_arm_gives_the_same_task_framing(prompts, request_under_test):
    """The work, the module, the build command, the stopping rule: identical."""
    module = request_under_test.module_path
    for name, prompt in prompts.items():
        assert f"module at {module}" in prompt, name
        assert f"./mvnw --batch-mode -pl {module} -am test" in prompt, name
        assert "Do not change any other module." in prompt, name
        assert "existing tests must still pass" in prompt, name
        assert "Do not commit" in prompt, name


def representation(name: str, request: cr.ChangeRequest, workspace: Path) -> str:
    """Everything an arm puts in front of the agent: the prompt and what it wrote."""
    arm = load_arm(name)
    arm.prepare(request, workspace)
    written = "\n".join(
        path.read_text(errors="ignore") for path in sorted(workspace.rglob("*")) if path.is_file()
    )
    return arm.prompt(request, workspace) + "\n" + written


def test_every_arm_carries_the_same_content(request_under_test, tmp_path):
    """Different representations of one change request, not different requests.

    An arm's representation is its prompt together with whatever it writes into
    the workspace, so the comparison has to take in both.
    """
    for name in ARMS:
        workspace = tmp_path / f"content-{name}"
        workspace.mkdir()
        rendered = " ".join(representation(name, request_under_test, workspace).split())
        assert request_under_test.id in rendered, name
        assert request_under_test.title in rendered, name
        for behaviour in request_under_test.behaviours:
            opening = " ".join(behaviour.statement.split()[:6])
            assert opening in rendered, f"{name}: {behaviour.id}"
        for boundary in request_under_test.boundaries:
            opening = " ".join(boundary.statement.split()[:5])
            assert opening in rendered, f"{name}: {boundary.id}"


def test_no_arm_leaks_the_ground_truth(prompts, request_under_test):
    for name, prompt in prompts.items():
        for invariant in request_under_test.must_invariants:
            assert invariant.id not in prompt, name
            if invariant.pattern:
                assert invariant.pattern not in prompt, name
        for check in request_under_test.acceptance:
            assert check.id not in prompt, name
            assert check.simple_class_name not in prompt, name
            assert check.destination not in prompt, name


def test_no_arm_writes_the_ground_truth_into_the_workspace(request_under_test, tmp_path):
    for name in ARMS:
        workspace = tmp_path / name
        workspace.mkdir()
        load_arm(name).prepare(request_under_test, workspace)
        written = "\n".join(
            path.read_text(errors="ignore") for path in workspace.rglob("*") if path.is_file()
        )
        for check in request_under_test.acceptance:
            assert check.simple_class_name not in written, name
        for invariant in request_under_test.must_invariants:
            assert invariant.id not in written, name


# --- what must differ ------------------------------------------------------


def test_the_baseline_puts_the_request_in_prose(prompts):
    prompt = prompts["baseline"]
    assert "The change request," in prompt
    assert "json" not in prompt.lower()


def test_the_ir_arms_hand_over_typed_documents(request_under_test, tmp_path):
    for name in ("lcir", "lcir_no_ast"):
        workspace = tmp_path / name
        workspace.mkdir()
        placed = load_arm(name).prepare(request_under_test, workspace)["artifacts"]
        assert any(path.endswith("intent-graph.json") for path in placed), name
        assert any(path.endswith("constraint-graph.json") for path in placed), name
        intent = json.loads((workspace / "change-request" / "intent-graph.json").read_text())
        assert intent["kind"] == "intent_graph"
        assert len(intent["behaviors"]) == len(request_under_test.behaviours)


def test_only_the_full_ir_arm_asks_for_addressed_operations(prompts):
    """That is the ablation: same typed intent, different edit representation."""
    assert "transformation-plan.json" in prompts["lcir"]
    assert "tree-sitter" in prompts["lcir"]
    assert "transformation-plan.json" not in prompts["lcir_no_ast"]
    assert "tree-sitter" not in prompts["lcir_no_ast"]


def test_the_ir_arms_are_otherwise_the_same(prompts):
    full = prompts["lcir"]
    ablated = prompts["lcir_no_ast"]
    shared = "Read the bundle. It is the specification; there is no prose version of it."
    assert shared in full and shared in ablated


def test_the_compressed_arm_is_the_smallest_representation(prompts, request_under_test):
    """It carries the same content in the fewest characters it can."""
    presentations = {}
    workspace = Path("/tmp")
    for name in ARMS:
        presentations[name] = load_arm(name).presentation(request_under_test, workspace)
    assert len(presentations["compressed"]) < len(presentations["baseline"])
    assert (
        " "
        not in json.dumps(
            json.loads(presentations["compressed"].splitlines()[-1]), separators=(",", ":")
        )[:20]
    )


def test_the_compressed_arm_keeps_every_behaviour(request_under_test):
    from pipelines.compressed.arm import minify

    payload = json.loads(minify(request_under_test))
    assert len(payload["b"]) == len(request_under_test.behaviours)
    assert len(payload["x"]) == len(request_under_test.boundaries)


# --- the prompt-iteration allowance ----------------------------------------


def test_every_arm_has_the_same_prompt_allowance():
    """An arm that was tuned more than another wins on effort, not representation."""
    recorded = arms_module.allowances()
    assert set(recorded) == set(ARMS)
    assert len({entry.allowance for entry in recorded.values()}) == 1
    for entry in recorded.values():
        assert entry.iterations_used <= entry.allowance


def test_a_cross_service_request_names_every_module_it_may_touch(tmp_path):
    """Naming only the first forbids the change the request asks for.

    The framing tells the agent to make the change in the named module and to
    leave every other module alone. With one module named, an agent on a
    cross-service change was instructed away from half its own task and then
    scored on hidden checks that run there.
    """
    request = next(item for item in cr.load_all() if len(item.modules) > 1)
    for name in ARMS:
        prompt = load_arm(name).prompt(request, tmp_path)
        for module_path in request.module_paths:
            assert module_path in prompt, f"{name} does not name {module_path}"


def test_a_single_module_prompt_is_unchanged_by_that(tmp_path):
    """One module joined with nothing is that module: those cells stay comparable."""
    request = next(item for item in cr.load_all() if len(item.modules) == 1)
    for name in ARMS:
        prompt = load_arm(name).prompt(request, tmp_path)
        assert f"Make the change in {request.module_path}." in prompt


def test_the_recorded_template_digests_match_the_arms():
    """The ledger records the template as frozen; a quiet edit shows up here."""
    recorded = arms_module.allowances()
    for name in ARMS:
        assert recorded[name].template_sha256 == load_arm(name).template_digest(), name


def test_the_arms_have_spent_the_same_number_of_iterations():
    used = {entry.iterations_used for entry in arms_module.allowances().values()}
    assert len(used) == 1


# --- what the IR arms do after the run -------------------------------------


def a_verification(status: str = "pass") -> dict:
    return {
        "verified_success": status == "pass",
        "acceptance": {"status": status},
        "invariants": [
            {
                "id": "invariant:existing-tests-pass",
                "kind": "module_tests_pass",
                "status": status,
                "detail": "",
            }
        ],
    }


def test_the_ir_arm_writes_a_bundle_and_projections_after_the_run(request_under_test, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    arm = load_arm("lcir")
    arm.prepare(request_under_test, workspace)
    result = arm.finalise(request_under_test, workspace, tmp_path, a_verification())

    bundle = tmp_path / result["bundle"]
    assert (bundle / "evidence-graph.json").exists()
    assert (bundle / "provenance-ledger.json").exists()
    assert sorted(result["projections"]) == [
        "change-summary.md",
        "incident-note.md",
        "user-story.md",
    ]
    for name in result["projections"]:
        assert (tmp_path / "projections" / name).read_text().strip()


def test_the_evidence_graph_records_what_verification_observed(request_under_test, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    arm = load_arm("lcir")
    arm.prepare(request_under_test, workspace)
    result = arm.finalise(request_under_test, workspace, tmp_path, a_verification("fail"))
    evidence = json.loads((tmp_path / result["bundle"] / "evidence-graph.json").read_text())
    statuses = {node["status"] for node in evidence["evidence"]}
    assert statuses == {"fail"}
    for behaviour in request_under_test.behaviours:
        assert any(
            f"acceptance:{behaviour.id}" in node["discharges"] for node in evidence["evidence"]
        )


def test_a_missing_transformation_plan_is_recorded_not_invented(request_under_test, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    arm = load_arm("lcir")
    arm.prepare(request_under_test, workspace)
    result = arm.finalise(request_under_test, workspace, tmp_path, a_verification())
    assert result["transformation_plan"] == "absent"
    assert result["bundle_validated"] is False


def test_an_invalid_transformation_plan_is_reported(request_under_test, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    arm = load_arm("lcir")
    arm.prepare(request_under_test, workspace)
    (workspace / "change-request" / "transformation-plan.json").write_text('{"kind": "wrong"}')
    result = arm.finalise(request_under_test, workspace, tmp_path, a_verification())
    assert result["transformation_plan"] == "invalid"
    assert result["transformation_plan_problems"]


def test_a_valid_transformation_plan_completes_the_bundle(request_under_test, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    arm = load_arm("lcir")
    arm.prepare(request_under_test, workspace)
    behaviour = request_under_test.behaviours[0].id
    plan = {
        "kind": "transformation_plan",
        "ir_version": "0.1.0",
        "change_request": request_under_test.id,
        "implements": [f"acceptance:{behaviour}"],
        "respects": [f"constraint:{request_under_test.boundaries[0].id}"],
        "components": [
            {
                "id": f"component:{request_under_test.module}",
                "name": request_under_test.module_path,
                "repository": "https://example.invalid/app.git",
                "path": request_under_test.module_path,
                "language": "java",
            }
        ],
        "code_changes": [
            {
                "id": "edit:take-the-path-identifier",
                "component": f"component:{request_under_test.module}",
                "operation": "replace",
                "address": {
                    "binding": "tree-sitter",
                    "file": "src/main/java/Resource.java",
                    "language": "java",
                    "query": "(method_declaration) @target",
                },
                "payload": "// replacement",
                "implements": [f"acceptance:{behaviour}"],
            }
        ],
        "rollback": [
            {
                "id": "rollback:revert",
                "reverses": ["edit:take-the-path-identifier"],
                "strategy": "revert_commit",
                "procedure": "Revert the commit.",
            }
        ],
    }
    (workspace / "change-request" / "transformation-plan.json").write_text(json.dumps(plan))
    result = arm.finalise(request_under_test, workspace, tmp_path, a_verification())
    assert result["transformation_plan"] == "valid"
    assert result["bundle_problems"] == []
    assert result["bundle_validated"] is True
    summary = (tmp_path / "projections" / "change-summary.md").read_text()
    assert "edit:take-the-path-identifier" in summary or "Resource.java" in summary


def test_finalising_never_takes_a_cell_down(request_under_test, tmp_path, monkeypatch):
    """A defect in the arm's own bookkeeping must not lose the run that produced it."""
    from pipelines.common import runner
    from pipelines.common.executor import Execution

    monkeypatch.setattr(
        runner.executor,
        "execute",
        lambda *args, **kwargs: Execution(status="completed"),
    )
    monkeypatch.setattr(
        runner.verify,
        "verify",
        lambda *args, **kwargs: {"verified_success": True, "invariants": [], "changes": {}},
    )
    broken = load_arm("lcir")
    monkeypatch.setattr(
        type(broken),
        "finalise",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    cell = runner.Cell(request_under_test, "lcir", 1)
    record = runner.run_cell(cell, tmp_path / "runs")
    assert record.status == "completed"
    assert "boom" in record.arm_artifacts["error"]
