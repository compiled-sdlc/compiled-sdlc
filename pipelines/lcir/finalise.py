"""What the IR arms do with a run once the harness has verified it.

The evidence graph is written from what verification observed, the provenance
ledger from who did what, and the two are assembled with the intent and
constraint graphs — and the transformation plan, if the agent wrote a valid one
— into a bundle that is then validated as a whole.

The validation result is kept rather than acted on. A bundle that fails its
autonomy-tier obligation because an elevated-risk change was made unattended is
not a defect in the harness: it is the instrument reporting that the governance
the IR demands was not met, which is one of the things the experiment is for.

Nothing here is placed in the workspace. It all lands in the run's own
directory, after the agent has stopped.
"""

import json
import sys
from pathlib import Path

from pipelines.common import locks, telemetry
from pipelines.common.changerequests import ChangeRequest
from pipelines.lcir import compile as compiler

sys.path.insert(0, str(locks.REPO_ROOT / "lifecycle-ir"))

from lcir.bundle import load_bundle  # noqa: E402
from lcir.coverage import measure  # noqa: E402
from lcir.integrity import check_bundle  # noqa: E402
from lcir.schemas import validate_document  # noqa: E402

BUNDLE_DIRECTORY = "lifecycle-ir"
PLAN_NAME = "transformation-plan.json"


def agent_plan(workspace: Path) -> tuple[dict | None, list[str]]:
    """The transformation plan the agent wrote, and what is wrong with it."""
    path = workspace / "change-request" / PLAN_NAME
    if not path.exists():
        return None, ["the agent wrote no transformation plan"]
    try:
        document = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        return None, [f"the transformation plan is not valid JSON: {error}"]
    problems = validate_document(document, "transformation-plan", PLAN_NAME)
    return document, [problem.message for problem in problems]


def provenance_ledger(request: ChangeRequest, verification: dict, plan: dict | None) -> dict:
    """Who did what, in order, with the model that did it named from the pin."""
    model = locks.executor()["model"]["id"]
    covers = [change["id"] for change in (plan or {}).get("code_changes", [])]
    entries = [
        {
            "id": "entry:compile-intent",
            "sequence": 1,
            "action": "generate",
            "principal": "principal:harness",
            "summary": "Compiled the change request into typed intent and constraints.",
            "recorded_at": verification.get("observed_at", "1970-01-01T00:00:00Z"),
        },
        {
            "id": "entry:transform",
            "sequence": 2,
            "previous": "entry:compile-intent",
            "action": "transform",
            "principal": "principal:coding-agent",
            "summary": "Produced the change from the intent and constraint graphs.",
            "input_nodes": [f"behavior:{behaviour.id}" for behaviour in request.behaviours],
            "recorded_at": verification.get("observed_at", "1970-01-01T00:00:00Z"),
        },
        {
            "id": "entry:verify",
            "sequence": 3,
            "previous": "entry:transform",
            "action": "verify",
            "principal": "principal:harness",
            "summary": "Applied the hidden acceptance checks and the must-invariants.",
            "attests": [f"evidence:acceptance.{behaviour.id}" for behaviour in request.behaviours],
            "recorded_at": verification.get("observed_at", "1970-01-01T00:00:00Z"),
        },
    ]
    if covers:
        entries[1]["covers"] = covers
    return {
        "kind": "provenance_ledger",
        "ir_version": compiler.IR_VERSION,
        "change_request": request.id,
        "principals": [
            {
                "id": "principal:harness",
                "type": "tool",
                "name": "Experiment harness",
                "version": "0.1.0",
                "role": "Compiles intent, verifies the run, records what happened.",
            },
            {
                "id": "principal:coding-agent",
                "type": "agent",
                "name": "Pinned executor",
                "version": locks.executor()["cli"]["version"],
                "role": "Makes the change.",
            },
            {
                "id": "principal:model",
                "type": "model",
                "name": model,
                "version": locks.executor()["model"]["resolved_on"],
                "role": "Generates the material behind the change.",
            },
        ],
        "entries": entries,
    }


def finalise(
    request: ChangeRequest,
    workspace: Path,
    cell: Path,
    verification: dict,
    *,
    plan_expected: bool,
) -> dict:
    """Assemble, validate and project the run's IR. Never raises."""
    verification = {**verification, "observed_at": telemetry.now()}
    directory = cell / BUNDLE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)

    documents = compiler.documents(request)
    # The kept bundle records the invariants the run was scored against, which
    # the workspace copy does not carry; the evidence below discharges them.
    documents["constraint-graph.json"] = compiler.constraint_graph(request, include_invariants=True)
    documents["evidence-graph.json"] = compiler.evidence_graph(request, verification)
    documents["provenance-ledger.json"] = provenance_ledger(request, verification, None)

    plan, plan_problems = agent_plan(workspace)
    if plan is not None and not plan_problems:
        documents["transformation-plan.json"] = plan
        documents["provenance-ledger.json"] = provenance_ledger(request, verification, plan)

    for name, document in documents.items():
        (directory / name).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")

    manifest = {
        "kind": "lifecycle_ir_bundle",
        "ir_version": compiler.IR_VERSION,
        "change_request": request.id,
        "title": request.title,
        "created_at": verification["observed_at"],
        # A slot named here must be readable, so the plan appears only when the
        # run produced one. The ablation arm is never asked for a plan, and a
        # manifest that promised one would make its bundle unloadable and its
        # coverage unmeasurable.
        "documents": {
            name: document
            for name, document in (
                ("intent_graph", "intent-graph.json"),
                ("constraint_graph", "constraint-graph.json"),
                ("transformation_plan", "transformation-plan.json"),
                ("evidence_graph", "evidence-graph.json"),
                ("provenance_ledger", "provenance-ledger.json"),
            )
            if document in documents
        },
    }
    (directory / "bundle.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    # Every IR bundle is loaded and measured, whether or not a plan was written.
    # Obligations are discharged by the evidence graph and attributed by the
    # ledger, both of which the harness writes either way; measuring only the
    # bundles that carried a plan left the ablation arm with no figure at all
    # and made its governance look unobservable rather than merely planless.
    bundle, load_problems = load_bundle(directory)
    problems = [str(problem) for problem in load_problems]
    problems += [
        str(problem)
        for problem in check_bundle(bundle, bundle.nodes())
        if problem.severity == "error"
    ]
    # Recorded here so the evaluation can read them off the run record: the
    # metrics are computed from the records alone, never by re-reading the
    # bundles a run happened to leave behind.
    coverage, _ = measure(bundle, bundle.nodes())
    obligations_traced = round(coverage.obligations_traced, 4)
    # With no transformations at all the fraction is vacuously one. That is not
    # a governance success, so it is recorded as no figure rather than a perfect
    # one.
    transformations_attributed = (
        round(coverage.transformations_attributed, 4) if coverage.transformation_total > 0 else None
    )

    from projections import render

    rendered = render.write_all(request, documents, cell / "projections")

    return {
        "bundle": str(directory.name),
        "transformation_plan": (
            "valid"
            if plan is not None and not plan_problems
            else "invalid"
            if plan is not None
            else "absent"
        ),
        "transformation_plan_expected": plan_expected,
        "transformation_plan_problems": plan_problems[:5],
        "bundle_problems": problems[:10],
        # The bundle an arm owed: with a plan where one was expected, without
        # where none was. Requiring a plan of every arm scored the ablation arm
        # zero for not doing something it was never asked to do.
        "bundle_validated": bool(
            problems == [] and (not plan_expected or "transformation-plan.json" in documents)
        ),
        "tier_required": (
            documents["constraint-graph.json"]["risk"]["autonomy_tier"] in {"L2", "L3"}
        ),
        # Unknown, not satisfied, when there was no bundle to check it against:
        # an obligation nobody looked for is not an obligation met.
        "tier_satisfied": (
            None
            if "transformation-plan.json" not in documents
            else not any("tier-approval-missing" in problem for problem in problems)
        ),
        "obligations_traced": obligations_traced,
        "transformations_attributed": transformations_attributed,
        "projections": rendered,
    }
