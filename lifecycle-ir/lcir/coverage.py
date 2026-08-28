"""Traceability coverage of a bundle.

These are the completeness questions the Evidence Graph and Provenance Ledger exist
to answer: is every obligation discharged by something, and is every transformation
accounted for by someone. They are reported as warnings rather than errors because a
bundle mid-flight is legitimately incomplete; --strict is what turns them fatal.
"""

from dataclasses import dataclass

from lcir.bundle import Bundle
from lcir.model import Node, Problem


@dataclass
class Coverage:
    """Counts behind the traceability report."""

    acceptance_total: int = 0
    acceptance_discharged: int = 0
    must_constraint_total: int = 0
    must_constraint_discharged: int = 0
    transformation_total: int = 0
    transformation_with_provenance: int = 0
    transformation_with_evidence: int = 0
    open_questions: int = 0

    @staticmethod
    def _fraction(part: int, whole: int) -> float:
        return 1.0 if whole == 0 else part / whole

    @property
    def obligations_traced(self) -> float:
        """Fraction of acceptance conditions and must-constraints with passing evidence."""
        return self._fraction(
            self.acceptance_discharged + self.must_constraint_discharged,
            self.acceptance_total + self.must_constraint_total,
        )

    @property
    def transformations_attributed(self) -> float:
        """Fraction of transformations a ledger entry accounts for."""
        return self._fraction(self.transformation_with_provenance, self.transformation_total)


def measure(bundle: Bundle, nodes: dict[str, Node]) -> tuple[Coverage, list[Problem]]:
    """Count what is traced, and warn about what is not."""
    coverage = Coverage()
    problems: list[Problem] = []

    evidence = [
        item
        for item in (bundle.documents.get("evidence_graph") or {}).get("evidence", [])
        if isinstance(item, dict)
    ]
    entries = [
        entry
        for entry in (bundle.documents.get("provenance_ledger") or {}).get("entries", [])
        if isinstance(entry, dict)
    ]

    discharged_by_passing: set[str] = set()
    covered_by_evidence: set[str] = set()
    for item in evidence:
        targets = [target for target in item.get("discharges", []) if isinstance(target, str)]
        if item.get("status") == "pass":
            discharged_by_passing.update(targets)
        covered_by_evidence.update(
            target for target in item.get("covers", []) or [] if isinstance(target, str)
        )

    attributed: set[str] = set()
    for entry in entries:
        attributed.update(
            target for target in entry.get("covers", []) or [] if isinstance(target, str)
        )

    for node in nodes.values():
        if node.kind == "acceptance":
            coverage.acceptance_total += 1
            if node.id in discharged_by_passing:
                coverage.acceptance_discharged += 1
            else:
                problems.append(
                    Problem(
                        "warning",
                        "untraced-acceptance",
                        node.id,
                        "no passing evidence discharges this acceptance condition",
                    )
                )
        elif node.kind == "constraint" and node.data.get("obligation") == "must":
            coverage.must_constraint_total += 1
            if node.id in discharged_by_passing:
                coverage.must_constraint_discharged += 1
            else:
                problems.append(
                    Problem(
                        "warning",
                        "untraced-constraint",
                        node.id,
                        "no passing evidence discharges this must-constraint",
                    )
                )
        elif node.kind in {"edit", "deployment"}:
            coverage.transformation_total += 1
            if node.id in attributed:
                coverage.transformation_with_provenance += 1
            else:
                problems.append(
                    Problem(
                        "warning",
                        "unattributed-transformation",
                        node.id,
                        "no ledger entry accounts for this transformation",
                    )
                )
            if node.id in covered_by_evidence:
                coverage.transformation_with_evidence += 1
            else:
                problems.append(
                    Problem(
                        "warning",
                        "unverified-transformation",
                        node.id,
                        "no evidence was observed over this transformation",
                    )
                )
        elif node.kind == "question" and node.data.get("status") == "open":
            coverage.open_questions += 1
            problems.append(
                Problem(
                    "warning",
                    "open-question",
                    node.id,
                    "this question is unresolved; the intent is not settled",
                )
            )

    satisfied_goals = {
        goal
        for node in nodes.values()
        if node.kind == "behavior"
        for goal in node.data.get("satisfies", [])
    }
    implemented_clauses = {
        clause
        for node in nodes.values()
        if node.kind in {"edit", "deployment"}
        for clause in node.data.get("implements", []) or []
    }
    for node in nodes.values():
        if node.kind == "goal" and node.id not in satisfied_goals:
            problems.append(
                Problem("warning", "unrealised-goal", node.id, "no behavior realises this goal")
            )
        if node.kind == "behavior" and node.id not in implemented_clauses:
            acceptance = {
                condition.id
                for condition in nodes.values()
                if condition.kind == "acceptance" and node.id in condition.data.get("verifies", [])
            }
            if not acceptance & implemented_clauses:
                problems.append(
                    Problem(
                        "warning",
                        "unimplemented-behavior",
                        node.id,
                        "no code or deployment change implements this behavior, "
                        "directly or through one of its acceptance conditions",
                    )
                )
    return coverage, problems


def format_report(coverage: Coverage) -> str:
    """The traceability summary printed by the report command."""
    lines = [
        "traceability",
        f"  acceptance conditions discharged   {coverage.acceptance_discharged}"
        f"/{coverage.acceptance_total}",
        f"  must-constraints discharged        {coverage.must_constraint_discharged}"
        f"/{coverage.must_constraint_total}",
        f"  transformations with provenance    {coverage.transformation_with_provenance}"
        f"/{coverage.transformation_total}",
        f"  transformations with evidence      {coverage.transformation_with_evidence}"
        f"/{coverage.transformation_total}",
        f"  open questions                     {coverage.open_questions}",
        f"  obligations traced                 {coverage.obligations_traced:.2f}",
        f"  transformations attributed         {coverage.transformations_attributed:.2f}",
    ]
    return "\n".join(lines)
