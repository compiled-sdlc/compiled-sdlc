"""Tests for the Lifecycle IR schemas, examples and validator."""

import json
import shutil
from pathlib import Path

import pytest
from lcir import coverage as coverage_module
from lcir.bundle import Bundle, load_bundle
from lcir.cli import main, validate_bundle_at
from lcir.integrity import check_references, holders
from lcir.model import IR_VERSION, REFERENCES
from lcir.schemas import check_schema_set, load_schemas

REPO = Path(__file__).resolve().parents[1]
EXAMPLES = REPO / "lifecycle-ir" / "examples"
CR_014 = EXAMPLES / "change-request" / "CR-014"


def codes(problems) -> set[str]:
    return {problem.code for problem in problems}


def copy_bundle(tmp_path: Path) -> Path:
    destination = tmp_path / "CR-014"
    shutil.copytree(CR_014, destination)
    return destination


def edit(bundle_dir: Path, filename: str, mutate) -> None:
    path = bundle_dir / filename
    document = json.loads(path.read_text())
    mutate(document)
    path.write_text(json.dumps(document, indent=2))


# --- the schema set itself -------------------------------------------------


def test_schema_set_is_consistent():
    assert check_schema_set() == []


@pytest.mark.parametrize("name", sorted(load_schemas()))
def test_every_schema_is_identified_and_versioned(name):
    schema = load_schemas()[name]
    assert schema["$id"] == f"urn:compiled-sdlc:lifecycle-ir:0.1:{name}"
    assert schema["version"] == IR_VERSION
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


# --- the examples ----------------------------------------------------------


def test_examples_command_passes(capsys):
    assert main(["examples"]) == 0
    assert "examples passed" in capsys.readouterr().out


def test_end_to_end_bundle_is_fully_traced():
    bundle, problems = validate_bundle_at(CR_014)
    assert problems == [], "the end-to-end bundle must validate with no warnings"
    measured, _ = coverage_module.measure(bundle, bundle.nodes())
    assert measured.obligations_traced == 1.0
    assert measured.transformations_attributed == 1.0


def test_end_to_end_bundle_exercises_every_cross_link():
    """The example exists to demonstrate the linkage; every edge type must appear in it."""
    bundle, _ = load_bundle(CR_014)
    unexercised = [
        reference.label
        for reference in REFERENCES
        if not any(holder.get(reference.field) for _, holder in holders(bundle, reference))
    ]
    assert unexercised == []


def test_every_cross_link_resolves_to_an_accepted_kind():
    bundle, _ = load_bundle(CR_014)
    nodes = bundle.nodes()
    for reference in REFERENCES:
        for _, holder in holders(bundle, reference):
            raw = holder.get(reference.field)
            values = [raw] if isinstance(raw, str) else raw or []
            for value in values:
                assert nodes[value].kind in reference.targets


# --- referential integrity -------------------------------------------------


def test_dangling_reference_is_reported(tmp_path):
    bundle_dir = copy_bundle(tmp_path)
    edit(
        bundle_dir,
        "evidence-graph.json",
        lambda doc: doc["evidence"][0]["discharges"].append("acceptance:invented"),
    )
    assert "dangling-reference" in codes(validate_bundle_at(bundle_dir)[1])


def test_reference_to_the_wrong_kind_is_reported():
    """The reference table, not the identifier pattern, is what types an edge."""
    bundle = Bundle(
        directory=Path("."),
        manifest={},
        documents={
            "evidence_graph": {
                "evidence": [{"id": "evidence:a", "discharges": ["component:visits-service"]}]
            },
            "transformation_plan": {"components": [{"id": "component:visits-service"}]},
        },
    )
    problems = check_references(bundle, bundle.nodes())
    assert codes(problems) == {"reference-kind"}
    assert "this edge accepts acceptance, behavior, constraint" in problems[0].message


def test_duplicate_identifier_across_documents_is_reported(tmp_path):
    bundle_dir = copy_bundle(tmp_path)

    def duplicate(doc):
        first = json.loads(json.dumps(doc["evidence"][0]))
        first["id"] = doc["evidence"][1]["id"]
        doc["evidence"].append(first)

    edit(bundle_dir, "evidence-graph.json", duplicate)
    assert "duplicate-id" in codes(validate_bundle_at(bundle_dir)[1])


def test_broken_ledger_chain_is_reported(tmp_path):
    bundle_dir = copy_bundle(tmp_path)
    edit(
        bundle_dir,
        "provenance-ledger.json",
        lambda doc: doc["entries"][3].update({"previous": doc["entries"][0]["id"]}),
    )
    assert "ledger-chain" in codes(validate_bundle_at(bundle_dir)[1])


def test_gap_in_the_ledger_sequence_is_reported(tmp_path):
    bundle_dir = copy_bundle(tmp_path)

    def drop_middle(doc):
        del doc["entries"][3]

    edit(bundle_dir, "provenance-ledger.json", drop_middle)
    assert "ledger-sequence" in codes(validate_bundle_at(bundle_dir)[1])


def test_tier_requiring_approval_without_one_is_reported(tmp_path):
    bundle_dir = copy_bundle(tmp_path)
    edit(
        bundle_dir,
        "provenance-ledger.json",
        lambda doc: doc["entries"][6]["approval"].update({"tier": "L1"}),
    )
    problems = validate_bundle_at(bundle_dir)[1]
    assert "tier-approval-missing" in codes(problems)


def test_tier_not_requiring_approval_needs_none(tmp_path):
    bundle_dir = copy_bundle(tmp_path)

    def drop_approval(doc):
        del doc["entries"][6]
        for index, entry in enumerate(doc["entries"]):
            entry["sequence"] = index + 1
            if index == 0:
                entry.pop("previous", None)
            else:
                entry["previous"] = doc["entries"][index - 1]["id"]

    edit(bundle_dir, "provenance-ledger.json", drop_approval)
    edit(
        bundle_dir, "constraint-graph.json", lambda doc: doc["risk"].update({"autonomy_tier": "L1"})
    )
    assert "tier-approval-missing" not in codes(validate_bundle_at(bundle_dir)[1])


def test_evidence_naming_the_wrong_check_is_reported(tmp_path):
    bundle_dir = copy_bundle(tmp_path)
    edit(
        bundle_dir,
        "evidence-graph.json",
        lambda doc: doc["evidence"][0].update({"check": "check:visits.rate-limit.under-limit"}),
    )
    assert "check-mismatch" in codes(validate_bundle_at(bundle_dir)[1])


def test_component_dependency_cycle_is_reported(tmp_path):
    bundle_dir = copy_bundle(tmp_path)
    edit(
        bundle_dir,
        "transformation-plan.json",
        lambda doc: doc["components"][0].update({"depends_on": ["component:api-gateway"]}),
    )
    problems = validate_bundle_at(bundle_dir)[1]
    assert "cycle" in codes(problems)


def test_document_declaring_another_change_request_is_reported(tmp_path):
    bundle_dir = copy_bundle(tmp_path)
    edit(bundle_dir, "evidence-graph.json", lambda doc: doc.update({"change_request": "CR-999"}))
    assert "change-request-mismatch" in codes(validate_bundle_at(bundle_dir)[1])


def test_document_declaring_another_ir_version_is_reported(tmp_path):
    bundle_dir = copy_bundle(tmp_path)
    edit(bundle_dir, "intent-graph.json", lambda doc: doc.update({"ir_version": "0.2.0"}))
    problems = validate_bundle_at(bundle_dir)[1]
    assert "version-mismatch" in codes(problems)


def test_missing_document_is_reported(tmp_path):
    bundle_dir = copy_bundle(tmp_path)
    (bundle_dir / "evidence-graph.json").unlink()
    problems = validate_bundle_at(bundle_dir)[1]
    assert "bundle-document" in codes(problems)
    assert "bundle-incomplete" in codes(problems)


# --- traceability ----------------------------------------------------------


def test_untraced_obligation_is_a_warning_not_an_error(tmp_path):
    """Evidence that failed still links correctly; what it no longer does is discharge."""
    bundle_dir = copy_bundle(tmp_path)

    def fail_contract_evidence(doc):
        for item in doc["evidence"]:
            if item["id"] == "evidence:contract-diff":
                item["status"] = "fail"

    edit(bundle_dir, "evidence-graph.json", fail_contract_evidence)
    problems = validate_bundle_at(bundle_dir)[1]
    assert not [problem for problem in problems if problem.severity == "error"]
    assert {"untraced-acceptance", "untraced-constraint"} <= codes(problems)


def test_strict_validation_fails_on_traceability_warnings(tmp_path, capsys):
    bundle_dir = copy_bundle(tmp_path)
    edit(
        bundle_dir,
        "provenance-ledger.json",
        lambda doc: doc["entries"][1].update({"covers": []}),
    )
    assert main(["validate", str(bundle_dir)]) == 0
    assert main(["validate", str(bundle_dir), "--strict"]) == 1
    assert "unattributed-transformation" in capsys.readouterr().out


def test_report_prints_the_traceability_summary(capsys):
    assert main(["report", str(CR_014)]) == 0
    out = capsys.readouterr().out
    assert "obligations traced                 1.00" in out
    assert "transformations attributed         1.00" in out


def test_single_document_validates_against_its_declared_schema(capsys):
    assert main(["validate", str(EXAMPLES / "valid" / "intent-graph.json")]) == 0
    assert main(["validate", str(EXAMPLES / "invalid" / "bundle-missing-structure.json")]) == 1
