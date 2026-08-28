"""The shape of a Lifecycle IR bundle: what holds nodes, and what may point at what.

The reference table below is the specification of the linkage between the five
structures. Each entry says: in this document, at this location, this field holds
identifiers, and they must resolve to a node of one of these kinds. Everything the
integrity checker knows about cross-structure references it reads from this table,
so adding a link type to the IR means adding a row here.
"""

from dataclasses import dataclass, field

IR_VERSION = "0.1.0"

# Document kind as declared by each document's "kind" property.
DOCUMENT_KINDS = {
    "intent_graph": "intent-graph",
    "constraint_graph": "constraint-graph",
    "transformation_plan": "transformation-plan",
    "evidence_graph": "evidence-graph",
    "provenance_ledger": "provenance-ledger",
}

# Where addressable nodes live, and the identifier kind each collection declares.
NODE_COLLECTIONS: dict[str, dict[str, str]] = {
    "intent_graph": {
        "actors": "actor",
        "goals": "goal",
        "behaviors": "behavior",
        "acceptance_conditions": "acceptance",
        "exclusions": "exclusion",
        "open_questions": "question",
    },
    "constraint_graph": {"constraints": "constraint"},
    "transformation_plan": {
        "components": "component",
        "code_changes": "edit",
        "deployment_changes": "deployment",
        "rollback": "rollback",
    },
    "evidence_graph": {"evidence": "evidence"},
    "provenance_ledger": {"principals": "principal", "entries": "entry"},
}

ALL_KINDS = frozenset(
    kind for collections in NODE_COLLECTIONS.values() for kind in collections.values()
)


@dataclass(frozen=True)
class Reference:
    """One typed edge type in the IR."""

    document: str
    path: tuple[str, ...]
    field: str
    targets: frozenset[str]
    description: str

    @property
    def label(self) -> str:
        location = ".".join((self.document, *self.path)) if self.path else self.document
        return f"{location}.{self.field}"


def _ref(document: str, path: tuple[str, ...], field_: str, targets, description: str) -> Reference:
    return Reference(document, path, field_, frozenset(targets), description)


REFERENCES: tuple[Reference, ...] = (
    # Within the Intent Graph.
    _ref("intent_graph", ("goals",), "stakeholders", {"actor"}, "goal is held by an actor"),
    _ref("intent_graph", ("behaviors",), "satisfies", {"goal"}, "behavior realises a goal"),
    _ref("intent_graph", ("behaviors",), "actors", {"actor"}, "behavior involves an actor"),
    _ref(
        "intent_graph",
        ("acceptance_conditions",),
        "verifies",
        {"goal", "behavior"},
        "acceptance condition decides a goal or behavior",
    ),
    _ref(
        "intent_graph",
        ("exclusions",),
        "scopes",
        {"goal", "behavior"},
        "exclusion bounds a goal or behavior",
    ),
    _ref(
        "intent_graph",
        ("open_questions",),
        "blocks",
        {"goal", "behavior", "acceptance"},
        "open question blocks an intent node",
    ),
    # Constraint Graph -> Intent Graph.
    _ref(
        "constraint_graph",
        ("constraints",),
        "applies_to",
        {"goal", "behavior", "acceptance"},
        "constraint bounds an intent node",
    ),
    # Transformation Plan -> Intent Graph and Constraint Graph.
    _ref(
        "transformation_plan",
        (),
        "implements",
        {"behavior", "acceptance"},
        "plan realises an intent clause",
    ),
    _ref(
        "transformation_plan", (), "respects", {"constraint"}, "plan is bounded by a constraint"
    ),
    _ref(
        "transformation_plan",
        ("components",),
        "depends_on",
        {"component"},
        "component depends on a component",
    ),
    _ref(
        "transformation_plan",
        ("code_changes",),
        "component",
        {"component"},
        "code change edits a component",
    ),
    _ref(
        "transformation_plan",
        ("code_changes",),
        "implements",
        {"behavior", "acceptance"},
        "code change realises an intent clause",
    ),
    _ref(
        "transformation_plan",
        ("code_changes",),
        "respects",
        {"constraint"},
        "code change is bounded by a constraint",
    ),
    _ref(
        "transformation_plan",
        ("deployment_changes",),
        "depends_on",
        {"edit"},
        "deployment change ships a code change",
    ),
    _ref(
        "transformation_plan",
        ("rollback",),
        "reverses",
        {"edit", "deployment"},
        "rollback undoes a transformation",
    ),
    # Evidence Graph -> Intent Graph, Constraint Graph, Transformation Plan.
    _ref(
        "evidence_graph",
        ("evidence",),
        "discharges",
        {"behavior", "acceptance", "constraint"},
        "evidence discharges an intent clause or constraint",
    ),
    _ref(
        "evidence_graph",
        ("evidence",),
        "covers",
        {"edit", "deployment"},
        "evidence was observed over a transformation",
    ),
    _ref(
        "evidence_graph",
        ("evidence",),
        "derived_from",
        {"evidence"},
        "evidence is derived from other evidence",
    ),
    # Provenance Ledger -> everything.
    _ref(
        "provenance_ledger", ("entries",), "principal", {"principal"}, "entry records who acted"
    ),
    _ref(
        "provenance_ledger",
        ("entries",),
        "previous",
        {"entry"},
        "entry names its predecessor in the chain",
    ),
    _ref(
        "provenance_ledger",
        ("entries",),
        "input_nodes",
        ALL_KINDS,
        "entry consumed an IR node",
    ),
    _ref(
        "provenance_ledger",
        ("entries",),
        "covers",
        {"edit", "deployment", "rollback"},
        "entry produced or executed a transformation",
    ),
    _ref(
        "provenance_ledger", ("entries",), "attests", {"evidence"}, "entry vouches for evidence"
    ),
    _ref(
        "provenance_ledger",
        ("entries", "approval"),
        "approver",
        {"principal"},
        "approval names the deciding principal",
    ),
    _ref(
        "provenance_ledger",
        ("entries", "approval"),
        "subjects",
        ALL_KINDS,
        "approval is about an IR node",
    ),
)


@dataclass
class Problem:
    """Something wrong with a bundle."""

    severity: str  # "error" or "warning"
    code: str
    location: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity}: [{self.code}] {self.location}: {self.message}"


@dataclass
class Node:
    """An addressable node found in a bundle."""

    id: str
    kind: str
    document: str
    collection: str
    data: dict = field(default_factory=dict)
