"""Projections: the human-readable views, generated from the IR.

Each of these is a back-end in the compiler analogy — a rendering of the same
canonical state for a particular reader. None of them is a source of truth, none
is edited by hand, and each is regenerated from the bundle whenever the bundle
changes. They exist to make the claim concrete: a story, a change summary and an
incident note are projections, not documents someone maintains.

They are rendered after a run, from the run's own bundle, into the run's
directory. Nothing here is ever placed in a workspace.
"""

from pathlib import Path

from pipelines.common.changerequests import ChangeRequest

STATUS_MARK = {"pass": "met", "fail": "not met", "inconclusive": "not established"}


def _behaviours(intent: dict) -> list[dict]:
    return intent.get("behaviors", [])


def _evidence_for(evidence: dict, target: str) -> list[dict]:
    return [node for node in evidence.get("evidence", []) if target in node.get("discharges", [])]


def user_story(request: ChangeRequest, documents: dict[str, dict]) -> str:
    """The story a delivery team would read."""
    intent = documents["intent-graph.json"]
    constraints = documents["constraint-graph.json"]
    goal = intent["goals"][0]
    lines = [
        f"# {request.id} — {intent['title']}",
        "",
        f"So that {goal['statement'][0].lower() + goal['statement'][1:]}",
        "",
        "## Acceptance",
        "",
    ]
    for condition in intent["acceptance_conditions"]:
        lines.append(f"- {condition['statement']}")
    lines += ["", "## Boundaries", ""]
    for constraint in constraints["constraints"]:
        lines.append(
            f"- ({constraint['obligation']}, {constraint['category']}) {constraint['statement']}"
        )
    lines += [
        "",
        f"Risk class {constraints['risk']['class']}, "
        f"autonomy tier {constraints['risk']['autonomy_tier']}.",
        "",
        "Generated from the Lifecycle IR. Edit the IR, not this.",
        "",
    ]
    return "\n".join(lines)


def change_summary(request: ChangeRequest, documents: dict[str, dict]) -> str:
    """The summary a reviewer would read on a proposed change."""
    intent = documents["intent-graph.json"]
    evidence = documents.get("evidence-graph.json", {})
    plan = documents.get("transformation-plan.json")
    lines = [f"# {request.id} — {intent['title']}", "", "## What changed", ""]
    if plan:
        for change in plan.get("code_changes", []):
            address = change.get("address", {})
            where = address.get("file") or address.get("recipe") or "unstated"
            lines.append(f"- `{change['operation']}` at {where} — {change.get('summary', '')}")
        for rollback in plan.get("rollback", []):
            lines.append(f"- rollback: {rollback['strategy']} — {rollback['procedure']}")
    else:
        lines.append("- The change was made without a stated transformation plan.")
    lines += ["", "## Whether it holds up", ""]
    for behaviour in _behaviours(intent):
        found = _evidence_for(evidence, behaviour["id"])
        state = STATUS_MARK.get(found[0]["status"], "not run") if found else "not run"
        lines.append(f"- {behaviour['statement']} — **{state}**")
    lines += ["", "Generated from the Lifecycle IR. Edit the IR, not this.", ""]
    return "\n".join(lines)


def incident_note(request: ChangeRequest, documents: dict[str, dict]) -> str:
    """The note an on-call engineer would read when this change is implicated."""
    intent = documents["intent-graph.json"]
    constraints = documents["constraint-graph.json"]
    evidence = documents.get("evidence-graph.json", {})
    unmet = [
        node
        for node in evidence.get("evidence", [])
        if node.get("status") in {"fail", "inconclusive"}
    ]
    lines = [
        f"# {request.id} — {intent['title']}",
        "",
        f"Category {request.category}. Risk class {constraints['risk']['class']}, "
        f"autonomy tier {constraints['risk']['autonomy_tier']}.",
        "",
        "## What this change was for",
        "",
        intent["goals"][0]["statement"],
        "",
        "## What was not established",
        "",
    ]
    if unmet:
        for node in unmet:
            lines.append(f"- {node['summary']} ({node['status']})")
    else:
        lines.append("- Every obligation in the bundle is discharged by passing evidence.")
    lines += ["", "## What to undo", ""]
    plan = documents.get("transformation-plan.json")
    if plan and plan.get("rollback"):
        for rollback in plan["rollback"]:
            lines.append(f"- {rollback['strategy']}: {rollback['procedure']}")
    else:
        lines.append("- No rollback was stated for this change.")
    lines += ["", "Generated from the Lifecycle IR. Edit the IR, not this.", ""]
    return "\n".join(lines)


PROJECTIONS = {
    "user-story.md": user_story,
    "change-summary.md": change_summary,
    "incident-note.md": incident_note,
}


def write_all(request: ChangeRequest, documents: dict[str, dict], directory: Path) -> list[str]:
    """Render every projection into a directory, reporting what was written."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for name, renderer in PROJECTIONS.items():
        (directory / name).write_text(renderer(request, documents))
        written.append(name)
    return written
