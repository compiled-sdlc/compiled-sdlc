"""The Governance Completeness Index.

Five things are asked of a run beyond whether it worked: did it state its change
as a plan that validates, did the plan and the evidence assemble into a bundle
that holds together, was the human decision its risk class demands recorded, is
every obligation discharged by evidence, and is every transformation accounted
for by the ledger.

Only the arms that produce IR can answer any of them. That is the point, and it
is reported as a capability rather than scored as a penalty: an arm with no IR
is not failing these checks, it has no way to take them, and neither has it any
way to notice when its own governance is incomplete. The asymmetry is itself a
finding — the baseline is exactly as unapproved as the IR arm that says so.

Every component therefore has three states, not two: scored, applicable but not
recorded, and not applicable at all. Collapsing the last two would confuse a
property of an arm with a gap in the data, and collapsing either into zero would
turn an unanswerable question into a failing grade.

A gap here never touches the success denominator. A run that passed the hidden
checks and violated no `must` invariant is a verified success even if its bundle
never assembled.
"""

import re
from collections import Counter
from dataclasses import dataclass

from eval.records import RunSet
from pipelines.lcir.finalise import GOVERNANCE_REVISION

COMPONENTS = {
    "plan_validity": "the change was stated as a transformation plan that validates",
    "bundle_assembly": "the bundle the arm owed assembled and validated",
    "tier_approval": "the human decision the risk class demands was recorded",
    "evidence_path": "every obligation is discharged by passing evidence",
    "provenance": "every transformation is accounted for by a ledger entry",
}


@dataclass(frozen=True)
class Reading:
    """One component read off one cell.

    `applies` says whether the question can be put to this cell at all;
    `value` is the answer when there is one. `comparable` is different from
    both: the question applies and may even have been answered, but under a
    definition that is no longer the current one, so the answer cannot be
    combined with answers taken under this one.
    """

    applies: bool
    value: float | None = None
    comparable: bool = True


NOT_APPLICABLE = Reading(applies=False)
NOT_COMPARABLE = Reading(applies=False, comparable=False)


def artifacts(record: dict) -> dict:
    return record.get("arm_artifacts") or {}


def produces_ir(record: dict) -> bool:
    """Whether this cell's arm produces IR at all."""
    return "transformation_plan" in artifacts(record)


def comparable(record: dict) -> bool:
    """Whether this cell's figures mean the same thing as the current ones.

    A change to the validator or the coverage rules changes what a figure *is*,
    not just its value. Averaging a figure taken under the old definition with
    one taken under the new produces a number that describes neither, so a
    record scored under a superseded revision is set aside until it is
    recomputed --- never quietly folded in.
    """
    return artifacts(record).get("governance_revision") == GOVERNANCE_REVISION


def states_a_plan(record: dict) -> bool:
    """Whether this arm is asked to state its change as a plan.

    The ablation arm is not, so it has no plan to validate and no
    transformations to attribute. Not writing one is compliance with its own
    instructions, never a governance gap. It does still assemble a bundle --
    intent, constraints, evidence and provenance -- and that bundle is scored.
    """
    return artifacts(record).get("transformation_plan_expected", False)


def plan_validity(record: dict) -> Reading:
    if not states_a_plan(record):
        return NOT_APPLICABLE
    if not comparable(record):
        return NOT_COMPARABLE
    return Reading(True, 1.0 if artifacts(record).get("transformation_plan") == "valid" else 0.0)


def bundle_assembly(record: dict) -> Reading:
    """Whether the bundle this arm owed assembled and validated.

    What an arm owes differs: with a plan where one was asked for, without
    where none was. Both IR arms owe a bundle, so both are scored on it;
    gating this on the plan excluded the ablation arm from a component it can
    take, and marked it down for obeying its own instructions.
    """
    if not produces_ir(record):
        return NOT_APPLICABLE
    if not comparable(record):
        return NOT_COMPARABLE
    return Reading(True, 1.0 if artifacts(record).get("bundle_validated") else 0.0)


def tier_approval(record: dict) -> Reading:
    """Only a cell whose risk class demands a decision can satisfy or miss one."""
    found = artifacts(record)
    if not produces_ir(record):
        return NOT_APPLICABLE
    if not comparable(record):
        return NOT_COMPARABLE
    if not found.get("tier_required"):
        return NOT_APPLICABLE
    satisfied = found.get("tier_satisfied")
    return Reading(True, None if satisfied is None else float(bool(satisfied)))


def evidence_path(record: dict) -> Reading:
    if not produces_ir(record):
        return NOT_APPLICABLE
    if not comparable(record):
        return NOT_COMPARABLE
    value = artifacts(record).get("obligations_traced")
    return Reading(True, None if value is None else float(value))


def provenance(record: dict) -> Reading:
    """Whether the ledger accounts for the transformations the run made.

    Only meaningful where there are transformations, which means only where a
    plan was asked for: with none, the fraction is vacuously one and would
    flatter the arm that wrote nothing.
    """
    if not states_a_plan(record):
        return NOT_APPLICABLE
    if not comparable(record):
        return NOT_COMPARABLE
    value = artifacts(record).get("transformations_attributed")
    return Reading(True, None if value is None else float(value))


READERS = {
    "plan_validity": plan_validity,
    "bundle_assembly": bundle_assembly,
    "tier_approval": tier_approval,
    "evidence_path": evidence_path,
    "provenance": provenance,
}


@dataclass(frozen=True)
class Component:
    """One component of the index for one arm."""

    name: str
    scored: int
    applicable_cells: int
    value: float | None
    #: Cells whose figures were taken under a superseded definition. They are
    #: neither scored nor counted against the arm; they are set aside, and said
    #: to have been, so a shrunken denominator is never mistaken for a full one.
    set_aside: int = 0

    @property
    def observable(self) -> bool:
        return self.value is not None

    @property
    def applicable(self) -> bool:
        return self.applicable_cells > 0

    @property
    def state(self) -> str:
        if self.observable:
            return "scored"
        if self.set_aside and not self.applicable:
            return "not comparable"
        return "not recorded" if self.applicable else "not observable"

    def to_dict(self) -> dict:
        return {
            "component": self.name,
            "state": self.state,
            "observable": self.observable,
            "applicable": self.applicable,
            "cells_applicable": self.applicable_cells,
            "cells_scored": self.scored,
            "cells_set_aside": self.set_aside,
            "value": None if self.value is None else round(self.value, 4),
        }


@dataclass(frozen=True)
class Index:
    """The governance index for one arm."""

    arm: str
    components: dict[str, Component]

    @property
    def observable(self) -> bool:
        return any(component.observable for component in self.components.values())

    @property
    def value(self) -> float | None:
        """The mean of the components that could be scored at all."""
        scored = [component.value for component in self.components.values() if component.observable]
        return sum(scored) / len(scored) if scored else None

    def to_dict(self) -> dict:
        return {
            "arm": self.arm,
            "observable": self.observable,
            "index": None if self.value is None else round(self.value, 4),
            "components": [
                self.components[name].to_dict() for name in COMPONENTS if name in self.components
            ],
        }


def component_for(records: tuple[dict, ...], name: str) -> Component:
    readings = [READERS[name](record) for record in records]
    scored = [reading.value for reading in readings if reading.value is not None]
    return Component(
        name=name,
        scored=len(scored),
        applicable_cells=sum(1 for reading in readings if reading.applies),
        value=(sum(scored) / len(scored)) if scored else None,
        set_aside=sum(1 for reading in readings if not reading.comparable),
    )


def index_for(run_set: RunSet, arm: str) -> Index:
    records = run_set.for_arm(arm)
    return Index(arm=arm, components={name: component_for(records, name) for name in COMPONENTS})


def indices(run_set: RunSet) -> list[Index]:
    return [index_for(run_set, arm) for arm in run_set.arms]


#: A bundle problem is reported as "error: [code] where: what". The code is the
#: part worth counting; the rest names one cell's particulars.
PROBLEM_CODE = re.compile(r"\[([a-z][a-z-]*)\]")

#: Reasons a bundle can fail for something no arm chose. An unattended run has
#: no human in it, so an approval the risk class demands is never recorded --- by
#: the design of the experiment, not by anything an arm did.
STRUCTURAL_CODES = frozenset({"tier-approval-missing"})


def assembly_failures(run_set: RunSet, arm: str) -> dict:
    """Why bundle assembly failed for this arm, by reason.

    Assembly is a single pass or fail, and a low figure invites the reading that
    the arm assembled a poor bundle. Counting the reasons separates the ones an
    arm could have avoided from the ones nobody could.
    """
    reasons: Counter = Counter()
    failed = structural_only = 0
    scored = 0
    for record in run_set.for_arm(arm):
        found = artifacts(record)
        if not produces_ir(record) or not comparable(record):
            continue
        scored += 1
        if found.get("bundle_validated"):
            continue
        failed += 1
        codes = {
            match.group(1)
            for problem in found.get("bundle_problems") or []
            if (match := PROBLEM_CODE.search(problem))
        }
        reasons.update(codes)
        if codes and codes <= STRUCTURAL_CODES:
            structural_only += 1
    return {
        "arm": arm,
        "bundles_scored": scored,
        "bundles_failed": failed,
        "failed_for_structural_reasons_only": structural_only,
        "reasons": dict(reasons.most_common()),
    }


def assembly_taxonomy(run_set: RunSet) -> list[dict]:
    return [
        assembly_failures(run_set, arm)
        for arm in run_set.arms
        if assembly_failures(run_set, arm)["bundles_scored"]
    ]
