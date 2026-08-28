"""Tests for compiling a change request into Lifecycle IR.

The IR arms stand or fall on this: the typed bundle has to be a faithful,
complete rendering of the same change request the other arms are given, and it
has to validate against the schemas the IR is defined by.
"""

import sys
from pathlib import Path

import pytest

from pipelines.common import changerequests as cr
from pipelines.lcir import compile as compiler

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lifecycle-ir"))

from lcir.schemas import validate_document  # noqa: E402


@pytest.fixture(scope="module")
def pilot() -> list[cr.ChangeRequest]:
    return cr.load_all()


@pytest.mark.parametrize("name", ["intent-graph", "constraint-graph"])
def test_every_compiled_document_validates(pilot, name):
    for request in pilot:
        document = compiler.documents(request)[f"{name}.json"]
        problems = validate_document(document, name, name)
        assert problems == [], f"{request.id}: {[p.message for p in problems]}"


def test_the_intent_graph_carries_every_behaviour(pilot):
    for request in pilot:
        intent = compiler.intent_graph(request)
        assert len(intent["behaviors"]) == len(request.behaviours)
        assert len(intent["acceptance_conditions"]) == len(request.behaviours)
        for behaviour in request.behaviours:
            assert any(node["statement"] == behaviour.statement for node in intent["behaviors"]), (
                f"{request.id}: {behaviour.id}"
            )


def test_every_behaviour_is_settled_by_an_acceptance_condition(pilot):
    for request in pilot:
        intent = compiler.intent_graph(request)
        verified = {
            target
            for condition in intent["acceptance_conditions"]
            for target in condition["verifies"]
        }
        assert {node["id"] for node in intent["behaviors"]} <= verified


def test_the_constraint_graph_carries_every_stated_boundary(pilot):
    for request in pilot:
        constraints = compiler.constraint_graph(request)["constraints"]
        assert len(constraints) == len(request.boundaries)
        for boundary in request.boundaries:
            assert any(node["statement"] == boundary.statement for node in constraints)


def test_the_risk_class_assigns_the_autonomy_tier(pilot):
    for request in pilot:
        risk = compiler.constraint_graph(request)["risk"]
        assert risk["class"] == request.risk_class
        assert risk["autonomy_tier"] == compiler.AUTONOMY_TIER[request.risk_class]


def test_the_compiled_bundle_names_no_hidden_check(pilot):
    """Typed intent, never the ground truth."""
    for request in pilot:
        rendered = str(compiler.documents(request))
        for check in request.acceptance:
            assert check.id not in rendered
            assert check.simple_class_name not in rendered
        for invariant in request.must_invariants:
            assert invariant.id not in rendered


def test_the_kept_bundle_records_the_invariants_the_run_was_scored_against(pilot):
    """The workspace copy carries the stated boundaries; the kept copy carries both."""
    for request in pilot:
        visible = compiler.constraint_graph(request)
        kept = compiler.constraint_graph(request, include_invariants=True)
        assert len(kept["constraints"]) >= len(visible["constraints"])
        identifiers = {constraint["id"] for constraint in kept["constraints"]}
        for invariant in request.must_invariants:
            assert compiler.invariant_constraint_id(invariant.id) in identifiers


def test_the_evidence_graph_discharges_something_that_exists(pilot):
    """Evidence pointing at a clause no document defines is not traceability."""
    verification = {
        "acceptance": {"status": "pass"},
        "invariants": [
            {"id": invariant.id, "kind": invariant.kind, "status": "pass", "detail": ""}
            for invariant in cr.load_all()[0].must_invariants
        ],
        "observed_at": "2026-08-28T12:00:00Z",
    }
    for request in pilot:
        verification["invariants"] = [
            {"id": invariant.id, "kind": invariant.kind, "status": "pass", "detail": ""}
            for invariant in request.must_invariants
        ]
        intent = compiler.intent_graph(request)
        constraints = compiler.constraint_graph(request, include_invariants=True)
        defined = {node["id"] for node in intent["behaviors"]}
        defined |= {node["id"] for node in intent["acceptance_conditions"]}
        defined |= {node["id"] for node in constraints["constraints"]}
        for node in compiler.evidence_graph(request, verification)["evidence"]:
            for target in node["discharges"]:
                assert target in defined, f"{request.id}: {node['id']} -> {target}"


def test_a_failing_verification_produces_failing_evidence(pilot):
    verification = {"acceptance": {"status": "fail"}, "invariants": []}
    for request in pilot:
        evidence = compiler.evidence_graph(request, verification)["evidence"]
        assert {node["status"] for node in evidence} == {"fail"}


def test_verification_that_could_not_run_is_inconclusive_not_passing(pilot):
    verification = {"acceptance": {"status": "error"}, "invariants": []}
    evidence = compiler.evidence_graph(pilot[0], verification)["evidence"]
    assert {node["status"] for node in evidence} == {"inconclusive"}
