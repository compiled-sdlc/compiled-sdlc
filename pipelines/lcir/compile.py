"""Compile a change request into Lifecycle IR.

The intent and constraint graphs are derived from the change request's own
decomposition — the same behaviours and boundaries every other arm is given, in
typed form rather than prose. Nothing is added: if it is not in the brief, it is
not in the IR.

The transformation plan is deliberately absent from what the agent is handed.
Producing it is the work: the agent states the change as addressed operations
before it makes them, and the harness validates what it wrote. The evidence
graph and the provenance ledger are the harness's to write, afterwards, from
what verification actually observed.

Acceptance conditions here reference checks named after the behaviours they
settle, not the hidden checks that score the run. The agent is given typed
intent, never the ground truth.
"""

from pipelines.common import locks
from pipelines.common.changerequests import ChangeRequest

IR_VERSION = "0.1.0"

AUTONOMY_TIER = {"low": "L1", "standard": "L1", "elevated": "L2", "critical": "L3"}
SEVERITY = {"must": "high", "should": "low"}
CHANGE_CLASS = {
    "low": "standard",
    "standard": "normal",
    "elevated": "normal",
    "critical": "emergency",
}


def slug(identifier: str) -> str:
    return identifier.lower()


def check_ref(request: ChangeRequest, behaviour_id: str) -> str:
    return f"check:{slug(request.id)}.{behaviour_id}"


def intent_graph(request: ChangeRequest) -> dict:
    """Goals, actors, behaviours and the conditions that settle them."""
    goal = f"goal:{slug(request.id)}"
    return {
        "kind": "intent_graph",
        "ir_version": IR_VERSION,
        "change_request": request.id,
        "title": request.title,
        "actors": [
            {
                "id": "actor:api-client",
                "name": "Calling client",
                "type": "external_system",
                "description": "Whatever calls the module over its interface.",
            },
            {
                "id": "actor:service",
                "name": request.module_path,
                "type": "service",
                "description": "The module the change is made in.",
            },
        ],
        "goals": [
            {
                "id": goal,
                "statement": request.title,
                "priority": "must",
                "stakeholders": ["actor:api-client"],
                "motivation": request.statement.strip(),
            }
        ],
        "behaviors": [
            {
                "id": f"behavior:{behaviour.id}",
                "statement": behaviour.statement,
                "satisfies": [goal],
                "actors": ["actor:api-client", "actor:service"],
            }
            for behaviour in request.behaviours
        ],
        "acceptance_conditions": [
            {
                "id": f"acceptance:{behaviour.id}",
                "statement": behaviour.statement,
                "verifies": [f"behavior:{behaviour.id}"],
                "check": {
                    "binding": "test",
                    "ref": check_ref(request, behaviour.id),
                    "description": "Discharged by the module's tests for this behaviour.",
                },
            }
            for behaviour in request.behaviours
        ],
    }


def invariant_constraint_id(invariant_id: str) -> str:
    """The constraint an invariant corresponds to in the graph."""
    return f"constraint:{invariant_id.removeprefix('invariant:')}"


def constraint_graph(request: ChangeRequest, *, include_invariants: bool = False) -> dict:
    """The boundaries the change is bounded by, and the autonomy tier they assign.

    The version handed to an agent carries only the boundaries the change
    request states openly. The version the harness keeps afterwards also carries
    the invariants it scored the run against, so that the evidence recording
    whether each was met has something to discharge. The agent is never shown
    the second one.
    """
    goal = f"goal:{slug(request.id)}"
    constraints = [
        {
            "id": f"constraint:{boundary.id}",
            "category": boundary.category,
            "statement": boundary.statement,
            "obligation": boundary.obligation,
            "severity": SEVERITY[boundary.obligation],
            "applies_to": [goal],
        }
        for boundary in request.boundaries
    ]
    if not constraints:
        constraints = [
            {
                "id": "constraint:module-scope",
                "category": "architecture",
                "statement": f"The change is confined to {request.module_path}.",
                "obligation": "must",
                "severity": "high",
                "applies_to": [goal],
            }
        ]
    if include_invariants:
        declared = {constraint["id"] for constraint in constraints}
        for invariant in request.must_invariants:
            identifier = invariant_constraint_id(invariant.id)
            if identifier in declared:
                continue
            declared.add(identifier)
            constraints.append(
                {
                    "id": identifier,
                    "category": "architecture",
                    "statement": invariant.statement,
                    "obligation": "must",
                    "severity": "high",
                    "applies_to": [goal],
                    "source": "A must-invariant the harness scores the run against.",
                }
            )
    return {
        "kind": "constraint_graph",
        "ir_version": IR_VERSION,
        "change_request": request.id,
        "risk": {
            "class": request.risk_class,
            "autonomy_tier": AUTONOMY_TIER[request.risk_class],
            "change_class": CHANGE_CLASS[request.risk_class],
            "rationale": f"Risk class {request.risk_class} for a {request.category} change.",
        },
        "constraints": constraints,
    }


def component(request: ChangeRequest) -> dict:
    """The one component the change is allowed to touch."""
    return {
        "id": f"component:{request.module}",
        "name": request.module_path,
        "repository": locks.target()["target"]["repository"],
        "path": request.module_path,
        "language": "java",
    }


def evidence_graph(request: ChangeRequest, verification: dict) -> dict:
    """What verification observed, as evidence against the intent it discharges.

    Written by the harness after the run, from the hidden checks and the
    invariants. It is never placed in a workspace: it is the record of how the
    run was judged, not an input to it.
    """
    observed = verification.get("acceptance", {}).get("status", "not_run")
    status = {"pass": "pass", "fail": "fail", "error": "inconclusive"}.get(observed, "not_run")
    evidence = [
        {
            "id": f"evidence:acceptance.{behaviour.id}",
            "kind": "test",
            "status": status,
            "summary": f"Hidden acceptance checks for {request.id}.",
            "discharges": [f"acceptance:{behaviour.id}", f"behavior:{behaviour.id}"],
            "check": check_ref(request, behaviour.id),
            "observed_at": verification.get("observed_at", "1970-01-01T00:00:00Z"),
        }
        for behaviour in request.behaviours
    ]
    for invariant in verification.get("invariants", []):
        target = invariant_constraint_id(invariant["id"])
        evidence.append(
            {
                "id": f"evidence:{invariant['id'].removeprefix('invariant:')}",
                "kind": "static_analysis" if invariant["kind"] != "module_tests_pass" else "test",
                "status": {"pass": "pass", "fail": "fail", "error": "inconclusive"}.get(
                    invariant["status"], "not_run"
                ),
                "summary": invariant.get("detail") or invariant["kind"],
                "discharges": [target],
                "observed_at": verification.get("observed_at", "1970-01-01T00:00:00Z"),
            }
        )
    return {
        "kind": "evidence_graph",
        "ir_version": IR_VERSION,
        "change_request": request.id,
        "evidence": evidence,
    }


def documents(request: ChangeRequest) -> dict[str, dict]:
    """The documents an arm places in a workspace before the run."""
    return {
        "intent-graph.json": intent_graph(request),
        "constraint-graph.json": constraint_graph(request),
    }
