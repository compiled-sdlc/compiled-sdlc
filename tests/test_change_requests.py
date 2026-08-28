"""Tests for the change-request format and the pilot set."""

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from pipelines.common import changerequests as cr

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def pilot() -> list[cr.ChangeRequest]:
    return cr.load_all()


def test_the_schema_is_valid():
    Draft202012Validator.check_schema(cr.schema())


def test_the_pilot_set_is_consistent():
    assert cr.check_set() == []


def test_the_pilot_set_has_five_change_requests(pilot):
    assert len(pilot) == 5
    assert [request.id for request in pilot] == ["CR-101", "CR-102", "CR-103", "CR-104", "CR-105"]


def test_the_pilot_set_covers_every_category(pilot):
    """All five IR structures are only exercised if the work varies in kind."""
    categories = {request.category for request in pilot}
    assert categories == set(cr.CATEGORIES)


def test_every_change_request_names_a_module_of_the_pin(pilot):
    for request in pilot:
        assert request.module_path.startswith("spring-petclinic-")


def test_every_change_request_has_invariants_and_a_hidden_check(pilot):
    for request in pilot:
        assert request.must_invariants, request.id
        assert request.acceptance, request.id
        kinds = {invariant.kind for invariant in request.must_invariants}
        assert "module_tests_pass" in kinds, f"{request.id} must keep the module's own tests green"


def test_every_hidden_check_exists_and_lands_in_its_module(pilot):
    for request in pilot:
        for check in request.acceptance:
            assert check.source.is_file()
            assert check.destination.startswith(request.module_path)
            assert check.destination.endswith(f"{check.simple_class_name}.java")
            assert check.simple_class_name in check.source.read_text()


# --- the guarantee that matters --------------------------------------------


def test_the_brief_carries_none_of_the_hidden_material(pilot):
    """What an arm may show the agent, and nothing that decides the outcome."""
    for request in pilot:
        rendered = json.dumps(request.brief())
        for invariant in request.must_invariants:
            assert invariant.id not in rendered
            assert invariant.statement not in rendered
            if invariant.pattern:
                assert invariant.pattern not in rendered
        for check in request.acceptance:
            assert check.id not in rendered
            assert check.simple_class_name not in rendered
            assert str(check.source) not in rendered
            assert check.destination not in rendered
            if check.statement:
                assert check.statement not in rendered


def test_the_brief_is_built_from_a_fixed_field_list(pilot):
    """A field added to the format is hidden until someone decides otherwise."""
    for request in pilot:
        assert set(request.brief()) == set(cr.BRIEF_FIELDS)


def test_a_new_field_does_not_leak_into_the_brief(tmp_path):
    document = yaml.safe_load((cr.CHANGE_REQUEST_DIR / "CR-101.yaml").read_text())
    request = cr.parse(document, tmp_path / "CR-101.yaml")
    assert "risk_class" not in request.brief(), "only the listed fields are rendered"


def test_the_hidden_checks_are_tracked_but_never_reachable_from_a_brief(pilot):
    """They are tracked openly; hidden means hidden from the agent."""
    for request in pilot:
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
