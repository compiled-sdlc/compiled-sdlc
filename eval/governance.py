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

from dataclasses import dataclass

from eval.records import RunSet

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
    `value` is the answer when there is one.
    """

    applies: bool
    value: float | None = None


NOT_APPLICABLE = Reading(applies=False)


def artifacts(record: dict) -> dict:
    return record.get("arm_artifacts") or {}


def produces_ir(record: dict) -> bool:
    """Whether this cell's arm produces IR at all."""
    return "transformation_plan" in artifacts(record)


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
    return Reading(True, 1.0 if artifacts(record).get("bundle_validated") else 0.0)


def tier_approval(record: dict) -> Reading:
    """Only a cell whose risk class demands a decision can satisfy or miss one."""
    found = artifacts(record)
    if not produces_ir(record):
        return NOT_APPLICABLE
    if "tier_required" in found:
        if not found["tier_required"]:
            return NOT_APPLICABLE
        satisfied = found.get("tier_satisfied")
        return Reading(True, None if satisfied is None else float(bool(satisfied)))
    # Older records carry the outcome only as a bundle problem, and only a
    # bundle that was checked carries one either way.
    if not found.get("bundle_validated") and not found.get("bundle_problems"):
        return NOT_APPLICABLE
    missing = any(
        "tier-approval-missing" in problem for problem in found.get("bundle_problems") or []
    )
    return Reading(True, 0.0 if missing else 1.0)


def evidence_path(record: dict) -> Reading:
    if not produces_ir(record):
        return NOT_APPLICABLE
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
        return "not recorded" if self.applicable else "not observable"

    def to_dict(self) -> dict:
        return {
            "component": self.name,
            "state": self.state,
            "observable": self.observable,
            "applicable": self.applicable,
            "cells_applicable": self.applicable_cells,
            "cells_scored": self.scored,
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
    )


def index_for(run_set: RunSet, arm: str) -> Index:
    records = run_set.for_arm(arm)
    return Index(arm=arm, components={name: component_for(records, name) for name in COMPONENTS})


def indices(run_set: RunSet) -> list[Index]:
    return [index_for(run_set, arm) for arm in run_set.arms]
