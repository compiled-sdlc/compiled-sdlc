"""Tests for the change-request format and the change-request set."""

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from pipelines.common import changerequests as cr

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def requests() -> list[cr.ChangeRequest]:
    return cr.load_all()


def test_the_schema_is_valid():
    Draft202012Validator.check_schema(cr.schema())


def test_the_set_is_consistent():
    assert cr.check_set() == []


def test_the_set_is_large_enough_and_has_no_gaps(requests):
    """The paper's set is 15 to 25 change requests, numbered without holes."""
    assert 15 <= len(requests) <= 25
    numbers = [int(request.id.removeprefix("CR-")) for request in requests]
    assert numbers == list(range(101, 101 + len(requests)))


def test_the_set_exercises_more_than_one_difficulty(requests):
    """The pilot scored every arm at every request; a set of one shape would again."""
    difficulties = {request.difficulty for request in requests}
    assert len(difficulties) >= 4, sorted(difficulties)
    assert difficulties <= set(cr.DIFFICULTIES)
    single = [r.id for r in requests if r.difficulty == "single_endpoint"]
    assert len(single) < len(requests) / 2, f"too many easy shapes: {single}"


def test_the_set_covers_every_category(requests):
    """All five IR structures are only exercised if the work varies in kind."""
    categories = {request.category for request in requests}
    assert categories == set(cr.CATEGORIES)


def test_every_change_request_names_a_module_of_the_pin(requests):
    for request in requests:
        assert request.module_paths
        for module_path in request.module_paths:
            assert module_path.startswith("spring-petclinic-")


def test_every_change_request_has_invariants_and_a_hidden_check(requests):
    for request in requests:
        assert request.must_invariants, request.id
        assert request.acceptance, request.id
        kinds = {invariant.kind for invariant in request.must_invariants}
        assert "module_tests_pass" in kinds, f"{request.id} must keep the module's own tests green"


def test_every_hidden_check_exists_and_lands_in_the_module_it_declares(requests):
    """A cross-service request places each check in the module that runs it."""
    from pipelines.common import locks

    for request in requests:
        for check in request.acceptance:
            assert check.source.is_file()
            assert check.module in request.modules, f"{request.id}: {check.id}"
            assert check.destination.startswith(locks.module_path(check.module))
            assert check.destination.endswith(f"{check.simple_class_name}.java")
            assert check.simple_class_name in check.source.read_text()


# --- the guarantee that matters --------------------------------------------


def test_the_brief_carries_none_of_the_hidden_material(requests):
    """What an arm may show the agent, and nothing that decides the outcome.

    A change request states its boundaries openly, and a stated boundary may
    have the same substance as an invariant the harness scores with — that is
    what a well-written change request does. What must never reach the agent is
    the ground truth itself: the identifiers the harness scores by, the patterns
    it matches, and everything about the hidden checks.
    """
    for request in requests:
        rendered = json.dumps(request.brief())
        for invariant in request.must_invariants:
            assert invariant.id not in rendered
            if invariant.pattern:
                assert invariant.pattern not in rendered
            for path in invariant.paths:
                assert path not in rendered
        for check in request.acceptance:
            assert check.id not in rendered
            assert check.simple_class_name not in rendered
            assert str(check.source) not in rendered
            assert check.destination not in rendered
            if check.statement:
                assert check.statement not in rendered


def test_every_incident_carries_runtime_evidence(requests):
    """An incident's premise is something observed, not something asserted."""
    incidents = [request for request in requests if request.category == "incident"]
    assert incidents, "the set has no incident change requests"
    for request in incidents:
        assert request.evidence is not None, f"{request.id} states its incident only in prose"
        assert request.evidence.artifacts, request.id
        for artifact in request.evidence.artifacts:
            assert artifact.path.is_file(), f"{request.id}: {artifact.id} is missing"
            assert artifact.read().strip(), f"{request.id}: {artifact.id} is empty"


def test_the_evidence_was_captured_against_the_current_pin(requests):
    for request in requests:
        assert cr.evidence_problems(request) == [], request.id


def test_the_evidence_gives_nothing_of_the_ground_truth_away(requests):
    """It is input the agent reads, so it must not name what scores the run."""
    for request in requests:
        if request.evidence is None:
            continue
        observed = "\n".join(artifact.read() for artifact in request.evidence.artifacts)
        observed += request.evidence.summary
        for invariant in request.must_invariants:
            assert invariant.id not in observed, request.id
        for check in request.acceptance:
            assert check.id not in observed, request.id
            assert check.simple_class_name not in observed, request.id


def test_the_brief_is_built_from_a_fixed_field_list(requests):
    """A field added to the format is hidden until someone decides otherwise."""
    for request in requests:
        assert set(request.brief()) == set(cr.BRIEF_FIELDS)


def test_a_new_field_does_not_leak_into_the_brief(tmp_path):
    document = yaml.safe_load((cr.CHANGE_REQUEST_DIR / "CR-101.yaml").read_text())
    request = cr.parse(document, tmp_path / "CR-101.yaml")
    assert "risk_class" not in request.brief(), "only the listed fields are rendered"


def test_the_hidden_checks_are_tracked_but_never_reachable_from_a_brief(requests):
    """They are tracked openly; hidden means hidden from the agent."""
    for request in requests:
        for check in request.acceptance:
            assert check.source.is_relative_to(cr.CHECKS_DIR)


# --- rejecting malformed change requests -----------------------------------


def a_document(**overrides) -> dict:
    document = yaml.safe_load((cr.CHANGE_REQUEST_DIR / "CR-101.yaml").read_text())
    document.update(overrides)
    return document


def test_an_unknown_category_is_rejected():
    assert any("category" in problem for problem in cr.validate(a_document(category="chore")))


def test_a_change_request_without_a_hidden_check_is_rejected():
    assert any("acceptance" in problem for problem in cr.validate(a_document(acceptance=[])))


def test_a_change_request_without_invariants_is_rejected():
    assert any(
        "must_invariants" in problem for problem in cr.validate(a_document(must_invariants=[]))
    )


def test_a_text_invariant_without_a_pattern_is_rejected():
    document = a_document(
        must_invariants=[
            {"id": "invariant:x", "kind": "text_present", "statement": "s", "paths": ["a"]}
        ]
    )
    assert any("pattern" in problem for problem in cr.validate(document))


def test_a_hidden_check_outside_the_checks_directory_is_rejected():
    document = a_document(
        acceptance=[
            {
                "id": "check:x",
                "source": "pipelines/common/leak.java",
                "destination": "spring-petclinic-customers-service/src/test/java/X.java",
                "test_class": "X",
            }
        ]
    )
    assert any("source" in problem for problem in cr.validate(document))


def test_loading_a_malformed_change_request_raises(tmp_path):
    path = tmp_path / "CR-999.yaml"
    path.write_text("id: CR-999\ntitle: incomplete\n")
    with pytest.raises(ValueError, match="CR-999.yaml"):
        cr.load(path)


def test_the_visible_boundaries_are_not_the_hidden_invariants(requests):
    """They may agree on substance; they are separate lists, scored separately."""
    for request in requests:
        stated = {boundary.id for boundary in request.boundaries}
        scored = {invariant.id for invariant in request.must_invariants}
        assert stated.isdisjoint(scored)
        assert all(invariant.id.startswith("invariant:") for invariant in request.must_invariants)


def test_every_change_request_decomposes_into_observable_behaviours(requests):
    """The arms represent the same content differently, so the content has to be one thing."""
    for request in requests:
        assert request.behaviours, request.id
        assert len({behaviour.id for behaviour in request.behaviours}) == len(request.behaviours)
        for behaviour in request.behaviours:
            assert behaviour.statement.strip()


def test_the_brief_carries_the_behaviours_and_boundaries(requests):
    for request in requests:
        brief = request.brief()
        assert len(brief["behaviours"]) == len(request.behaviours)
        assert len(brief["boundaries"]) == len(request.boundaries)
