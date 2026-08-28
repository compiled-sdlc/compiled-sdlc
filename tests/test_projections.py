"""Tests for the projections.

A projection is a rendering of the IR for a particular reader, not a document
anyone maintains. What is tested is that property: everything in a projection
comes from the bundle, and a projection changes when the bundle does.
"""

import pytest

from pipelines.common import changerequests as cr
from pipelines.lcir import compile as compiler
from projections import render


@pytest.fixture(scope="module")
def request_under_test() -> cr.ChangeRequest:
    return cr.load_all()[0]


def documents(request: cr.ChangeRequest, status: str = "pass") -> dict:
    verification = {
        "acceptance": {"status": status},
        "invariants": [],
        "observed_at": "2026-08-28T12:00:00Z",
    }
    prepared = compiler.documents(request)
    prepared["constraint-graph.json"] = compiler.constraint_graph(request, include_invariants=True)
    prepared["evidence-graph.json"] = compiler.evidence_graph(request, verification)
    return prepared


def test_every_projection_renders(request_under_test):
    prepared = documents(request_under_test)
    for name, renderer in render.PROJECTIONS.items():
        rendered = renderer(request_under_test, prepared)
        assert rendered.strip(), name
        assert request_under_test.id in rendered, name


def test_a_projection_says_it_is_generated(request_under_test):
    """A reader has to know which of the two to edit."""
    prepared = documents(request_under_test)
    for renderer in render.PROJECTIONS.values():
        assert "Edit the IR, not this." in renderer(request_under_test, prepared)


def test_the_story_carries_every_acceptance_condition_and_boundary(request_under_test):
    story = render.user_story(request_under_test, documents(request_under_test))
    for behaviour in request_under_test.behaviours:
        assert behaviour.statement in story
    for boundary in request_under_test.boundaries:
        assert boundary.statement in story


def test_the_summary_reports_what_the_evidence_said(request_under_test):
    passing = render.change_summary(request_under_test, documents(request_under_test, "pass"))
    failing = render.change_summary(request_under_test, documents(request_under_test, "fail"))
    assert "**met**" in passing
    assert "**not met**" in failing
    assert passing != failing, "a projection follows the bundle it was rendered from"


def test_the_summary_says_when_no_plan_was_stated(request_under_test):
    summary = render.change_summary(request_under_test, documents(request_under_test))
    assert "without a stated transformation plan" in summary


def test_the_incident_note_lists_what_was_not_established(request_under_test):
    note = render.incident_note(request_under_test, documents(request_under_test, "fail"))
    assert "What was not established" in note
    assert "fail" in note
    clean = render.incident_note(request_under_test, documents(request_under_test, "pass"))
    assert "Every obligation in the bundle is discharged" in clean


def test_the_incident_note_carries_the_risk_class_and_tier(request_under_test):
    note = render.incident_note(request_under_test, documents(request_under_test))
    assert request_under_test.risk_class in note
    assert "autonomy tier" in note


def test_projections_are_written_where_the_run_is_recorded(request_under_test, tmp_path):
    written = render.write_all(request_under_test, documents(request_under_test), tmp_path)
    assert sorted(written) == ["change-summary.md", "incident-note.md", "user-story.md"]
    for name in written:
        assert (tmp_path / name).read_text().strip()


def test_a_projection_holds_no_hidden_material(request_under_test):
    """They are rendered from the bundle, and the bundle carries no ground truth."""
    prepared = documents(request_under_test)
    for renderer in render.PROJECTIONS.values():
        rendered = renderer(request_under_test, prepared)
        for check in request_under_test.acceptance:
            assert check.simple_class_name not in rendered
            assert check.destination not in rendered


def test_every_projection_is_rendered_for_all_five_change_requests():
    for request in cr.load_all():
        prepared = documents(request)
        for name, renderer in render.PROJECTIONS.items():
            assert renderer(request, prepared).strip(), f"{request.id} {name}"
