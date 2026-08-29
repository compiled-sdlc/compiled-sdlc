"""Tests for the Governance Completeness Index.

The property under test is the ruling: what only some arms can be measured on is
reported as a capability, never scored as a penalty, and never allowed near the
success denominator.
"""

import pytest

from eval import governance
from pipelines.lcir.finalise import GOVERNANCE_REVISION
from tests.test_eval_records import a_record, a_run_set

FULL_IR = {
    # Every finalised record says which definition of these figures it was
    # scored under; one that does not is set aside rather than mixed in.
    "governance_revision": GOVERNANCE_REVISION,
    "transformation_plan": "valid",
    "transformation_plan_expected": True,
    "bundle_validated": True,
    "bundle_problems": [],
    "tier_required": True,
    "tier_satisfied": True,
    "obligations_traced": 1.0,
    "transformations_attributed": 1.0,
}


def ir_record(**overrides) -> dict:
    return a_record(arm="lcir", arm_artifacts={**FULL_IR, **overrides})


# --- the asymmetry ---------------------------------------------------------


def test_an_arm_with_no_ir_is_not_scored_at_all():
    """It is not failing these checks; it has no way to take them."""
    index = governance.index_for(a_run_set(a_record(arm="baseline")), "baseline")
    assert index.observable is False
    assert index.value is None
    for component in index.components.values():
        assert component.state == "not observable"
        assert component.value is None


def test_an_unobservable_component_is_never_a_zero():
    index = governance.index_for(a_run_set(a_record(arm="compressed")), "compressed")
    rendered = index.to_dict()
    assert rendered["index"] is None
    assert all(component["value"] is None for component in rendered["components"])
    assert all(component["state"] == "not observable" for component in rendered["components"])


def test_a_governance_gap_does_not_make_a_run_a_failure():
    """The ruling: success is hidden acceptance plus must-invariants, nothing else."""
    from eval import metrics

    run_set = a_run_set(
        ir_record(transformation_plan="invalid", bundle_validated=False, tier_satisfied=False)
    )
    assert metrics.salc(run_set, "lcir").verified_count == 1
    assert governance.index_for(run_set, "lcir").value < 1.0


# --- the three states ------------------------------------------------------


def test_a_scored_component_reports_its_fraction():
    run_set = a_run_set(ir_record(), ir_record(seed=2, transformation_plan="invalid"))
    component = governance.index_for(run_set, "lcir").components["plan_validity"]
    assert component.state == "scored"
    assert component.value == pytest.approx(0.5)
    assert component.scored == 2


def test_a_component_the_runs_did_not_record_is_not_a_zero():
    """The arm could be measured; these runs carry no figure."""
    artifacts = dict(FULL_IR)
    del artifacts["obligations_traced"]
    component = governance.component_for(
        (a_record(arm="lcir", arm_artifacts=artifacts),), "evidence_path"
    )
    assert component.state == "not recorded"
    assert component.value is None
    assert component.applicable is True


def test_an_arm_not_asked_for_a_plan_is_not_marked_down_for_lacking_one():
    """The ablation arm is complying with its own instructions.

    It has no plan to validate and no transformations to attribute, so those
    components do not apply to it. It does still assemble a bundle --- intent,
    constraints, evidence, provenance --- and is scored on that one, because a
    bundle it owed and did produce is not a governance gap.
    """
    record = a_record(
        arm="lcir_no_ast",
        arm_artifacts={
            "governance_revision": GOVERNANCE_REVISION,
            "transformation_plan": "absent",
            "transformation_plan_expected": False,
            "bundle_validated": True,
            "bundle_problems": [],
            "obligations_traced": 1.0,
            "transformations_attributed": None,
        },
    )
    index = governance.index_for(a_run_set(record), "lcir_no_ast")
    assert index.components["plan_validity"].state == "not observable"
    assert index.components["provenance"].state == "not observable"
    assert index.components["bundle_assembly"].value == 1.0
    assert index.components["evidence_path"].value == 1.0


# --- individual components -------------------------------------------------


def test_plan_validity_counts_only_valid_plans():
    assert governance.plan_validity(ir_record()).value == 1.0
    assert governance.plan_validity(ir_record(transformation_plan="invalid")).value == 0.0
    assert governance.plan_validity(ir_record(transformation_plan="absent")).value == 0.0


def test_bundle_assembly_follows_the_validator():
    assert governance.bundle_assembly(ir_record()).value == 1.0
    assert governance.bundle_assembly(ir_record(bundle_validated=False)).value == 0.0


def test_a_tier_that_demands_no_decision_is_not_scored():
    """Only an elevated risk class can satisfy or miss an approval."""
    assert governance.tier_approval(ir_record(tier_required=False)).applies is False


def test_a_missing_approval_scores_zero_where_one_was_required():
    assert governance.tier_approval(ir_record(tier_satisfied=False)).value == 0.0
    assert governance.tier_approval(ir_record(tier_satisfied=True)).value == 1.0


def test_an_unchecked_tier_is_unknown_rather_than_satisfied():
    """An obligation nobody looked for is not an obligation met."""
    reading = governance.tier_approval(ir_record(tier_satisfied=None))
    assert reading.applies is True
    assert reading.value is None


def test_a_record_scored_under_an_older_definition_is_set_aside():
    """Never mixed in: the figure meant something else when it was taken."""
    artifacts = {
        "transformation_plan": "valid",
        "transformation_plan_expected": True,
        "bundle_validated": False,
        "bundle_problems": [],
        "tier_required": True,
        "tier_satisfied": False,
        "obligations_traced": 1.0,
    }  # no governance_revision: written before the definition changed
    record = a_record(arm="lcir", arm_artifacts=artifacts)
    for reader in (governance.bundle_assembly, governance.tier_approval, governance.evidence_path):
        reading = reader(record)
        assert reading.comparable is False
        assert reading.value is None

    component = governance.component_for((record,), "bundle_assembly")
    assert component.state == "not comparable"
    assert component.set_aside == 1
    assert component.value is None


def test_a_tier_that_was_never_required_is_not_scored():
    assert governance.tier_approval(ir_record(tier_required=False)).applies is False


def test_evidence_and_provenance_coverage_are_read_as_fractions():
    record = ir_record(obligations_traced=0.75, transformations_attributed=0.5)
    assert governance.evidence_path(record).value == pytest.approx(0.75)
    assert governance.provenance(record).value == pytest.approx(0.5)


# --- the index itself ------------------------------------------------------


def test_the_index_averages_only_what_could_be_scored():
    artifacts = dict(FULL_IR)
    del artifacts["obligations_traced"]
    del artifacts["transformations_attributed"]
    index = governance.index_for(a_run_set(a_record(arm="lcir", arm_artifacts=artifacts)), "lcir")
    assert index.value == pytest.approx(1.0), "unmeasured components do not drag it down"


def test_a_partly_met_index_lands_between_the_extremes():
    run_set = a_run_set(
        ir_record(),
        ir_record(seed=2, transformation_plan="invalid", bundle_validated=False),
    )
    index = governance.index_for(run_set, "lcir")
    assert 0.0 < index.value < 1.0


def test_every_component_is_named_and_described():
    index = governance.index_for(a_run_set(ir_record()), "lcir")
    assert set(index.components) == set(governance.COMPONENTS)
    assert all(description for description in governance.COMPONENTS.values())


def test_indices_cover_every_arm_in_the_run_set():
    run_set = a_run_set(a_record(arm="baseline"), ir_record())
    assert [index.arm for index in governance.indices(run_set)] == ["baseline", "lcir"]
