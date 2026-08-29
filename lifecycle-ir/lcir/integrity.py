"""Referential integrity across the five structures.

Schema validation answers "is each document well formed". These checks answer the
question that matters for the IR: do the structures actually refer to each other,
and do the references resolve to the right kind of thing. A bundle whose documents
all validate but whose evidence discharges a clause no intent graph defines is not
a lifecycle representation; it is five files in a directory.
"""

from collections.abc import Iterator

from lcir.bundle import Bundle
from lcir.model import DOCUMENT_KINDS, REFERENCES, Node, Problem, Reference


def _walk(value, path: tuple[str, ...], location: str) -> Iterator[tuple[str, dict]]:
    """Yield every object reachable at `path`, expanding lists on the way."""
    if isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, path, f"{location}[{index}]")
        return
    if not isinstance(value, dict):
        return
    if not path:
        yield location, value
        return
    key = path[0]
    if key in value:
        yield from _walk(value[key], path[1:], f"{location}.{key}")


def holders(bundle: Bundle, reference: Reference) -> Iterator[tuple[str, dict]]:
    document = bundle.documents.get(reference.document)
    if document is None:
        return
    yield from _walk(document, reference.path, reference.document)


def _values(holder: dict, field: str) -> list[str]:
    raw = holder.get(field)
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str)]
    return []


def check_headers(bundle: Bundle, required: tuple[str, ...] = DOCUMENT_KINDS) -> list[Problem]:
    """Every document declares the same version and change request as the manifest.

    `required` is the set of slots this bundle owes. It defaults to all of them,
    because a complete bundle carries all of them; a caller that legitimately
    owes fewer — a run that was never asked to state a transformation plan —
    says so rather than having the missing slot reported as an error it could
    not have avoided.
    """
    problems = []
    version = bundle.manifest.get("ir_version")
    change_request = bundle.manifest.get("change_request")
    for slot in DOCUMENT_KINDS:
        document = bundle.documents.get(slot)
        if document is None:
            if slot not in required:
                continue
            problems.append(
                Problem(
                    "error",
                    "bundle-incomplete",
                    f"bundle.json#/documents/{slot}",
                    "the manifest does not name a readable document for this slot",
                )
            )
            continue
        if document.get("kind") != slot:
            problems.append(
                Problem(
                    "error",
                    "document-kind",
                    f"{slot}#/kind",
                    f"document declares kind {document.get('kind')!r} in the {slot} slot",
                )
            )
        if document.get("ir_version") != version:
            problems.append(
                Problem(
                    "error",
                    "version-mismatch",
                    f"{slot}#/ir_version",
                    f"document declares {document.get('ir_version')!r}, "
                    f"the manifest declares {version!r}",
                )
            )
        if document.get("change_request") != change_request:
            problems.append(
                Problem(
                    "error",
                    "change-request-mismatch",
                    f"{slot}#/change_request",
                    f"document declares {document.get('change_request')!r}, "
                    f"the manifest declares {change_request!r}",
                )
            )
    return problems


def check_identifiers(bundle: Bundle) -> list[Problem]:
    """Identifiers are unique across the whole bundle, not merely within a document."""
    return [
        Problem("error", "duplicate-id", location, f"identifier {identifier!r} is already defined")
        for identifier, location in bundle.duplicate_ids()
    ]


def check_references(bundle: Bundle, nodes: dict[str, Node]) -> list[Problem]:
    """Every cross-reference resolves, and resolves to a node of an accepted kind."""
    problems = []
    for reference in REFERENCES:
        for location, holder in holders(bundle, reference):
            where = holder.get("id") or location
            for value in _values(holder, reference.field):
                target = nodes.get(value)
                if target is None:
                    problems.append(
                        Problem(
                            "error",
                            "dangling-reference",
                            f"{where}.{reference.field}",
                            f"points at {value!r}, which no document in the bundle defines "
                            f"({reference.description})",
                        )
                    )
                elif target.kind not in reference.targets:
                    expected = ", ".join(sorted(reference.targets))
                    problems.append(
                        Problem(
                            "error",
                            "reference-kind",
                            f"{where}.{reference.field}",
                            f"points at {value!r}, a {target.kind} node; "
                            f"this edge accepts {expected}",
                        )
                    )
    return problems


def check_ledger_chain(bundle: Bundle) -> list[Problem]:
    """The ledger is a chain: contiguous sequence numbers, each entry naming the last."""
    ledger = bundle.documents.get("provenance_ledger")
    if not ledger:
        return []
    entries = [entry for entry in ledger.get("entries", []) if isinstance(entry, dict)]
    if not entries:
        return []
    problems = []
    by_sequence: dict[int, dict] = {}
    for entry in entries:
        sequence = entry.get("sequence")
        if not isinstance(sequence, int):
            continue
        if sequence in by_sequence:
            problems.append(
                Problem(
                    "error",
                    "ledger-sequence",
                    entry.get("id", "?"),
                    f"sequence {sequence} is already used by {by_sequence[sequence].get('id')!r}",
                )
            )
            continue
        by_sequence[sequence] = entry

    expected = set(range(1, len(by_sequence) + 1))
    for missing in sorted(expected - by_sequence.keys()):
        problems.append(
            Problem(
                "error",
                "ledger-sequence",
                "provenance_ledger",
                f"the chain has no entry with sequence {missing}",
            )
        )

    for sequence, entry in sorted(by_sequence.items()):
        previous = entry.get("previous")
        if sequence == 1:
            if previous is not None:
                problems.append(
                    Problem(
                        "error",
                        "ledger-chain",
                        entry.get("id", "?"),
                        "the first entry must not name a predecessor",
                    )
                )
            continue
        predecessor = by_sequence.get(sequence - 1)
        if predecessor is None:
            continue
        if previous != predecessor.get("id"):
            problems.append(
                Problem(
                    "error",
                    "ledger-chain",
                    entry.get("id", "?"),
                    f"names {previous!r} as its predecessor, but the entry at sequence "
                    f"{sequence - 1} is {predecessor.get('id')!r}",
                )
            )
    return problems


def check_autonomy_tier(bundle: Bundle) -> list[Problem]:
    """A tier that requires a human decision must have one recorded in the ledger."""
    constraints = bundle.documents.get("constraint_graph") or {}
    ledger = bundle.documents.get("provenance_ledger") or {}
    tier = (constraints.get("risk") or {}).get("autonomy_tier")
    if tier not in {"L2", "L3"}:
        return []
    for entry in ledger.get("entries", []):
        if not isinstance(entry, dict):
            continue
        approval = entry.get("approval")
        if isinstance(approval, dict) and approval.get("tier") == tier:
            return []
    return [
        Problem(
            "error",
            "tier-approval-missing",
            "provenance_ledger.entries",
            f"the constraint graph assigns autonomy tier {tier}, which requires a human "
            f"decision, but no ledger entry records an approval at that tier",
        )
    ]


def check_check_references(bundle: Bundle, nodes: dict[str, Node]) -> list[Problem]:
    """Evidence that names a check must name the check its acceptance condition names."""
    evidence_graph = bundle.documents.get("evidence_graph") or {}
    problems = []
    for item in evidence_graph.get("evidence", []):
        if not isinstance(item, dict):
            continue
        check = item.get("check")
        if not isinstance(check, str):
            continue
        conditions = [
            nodes[target]
            for target in item.get("discharges", [])
            if isinstance(target, str) and target in nodes and nodes[target].kind == "acceptance"
        ]
        if not conditions:
            continue
        expected = {
            condition.data.get("check", {}).get("ref")
            for condition in conditions
            if isinstance(condition.data.get("check"), dict)
        }
        if check not in expected:
            named = ", ".join(sorted(str(ref) for ref in expected if ref))
            problems.append(
                Problem(
                    "error",
                    "check-mismatch",
                    f"{item.get('id', '?')}.check",
                    f"names {check!r}, but the acceptance conditions it discharges are "
                    f"decided by {named or 'no check'}",
                )
            )
    return problems


def _cycles(edges: dict[str, list[str]]) -> list[list[str]]:
    """Every cycle reachable in a small directed graph, as node paths."""
    found: list[list[str]] = []
    state: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> None:
        state[node] = 1
        stack.append(node)
        for successor in edges.get(node, []):
            if state.get(successor) == 1:
                found.append(stack[stack.index(successor) :] + [successor])
            elif state.get(successor, 0) == 0 and successor in edges:
                visit(successor, stack)
        stack.pop()
        state[node] = 2

    for node in edges:
        if state.get(node, 0) == 0:
            visit(node, [])
    return found


def check_acyclic(bundle: Bundle) -> list[Problem]:
    """Component dependencies and evidence derivation must not run in circles."""
    problems = []
    graphs = {
        "component depends_on": _edges(bundle, "transformation_plan", "components", "depends_on"),
        "evidence derived_from": _edges(bundle, "evidence_graph", "evidence", "derived_from"),
    }
    for label, edges in graphs.items():
        for cycle in _cycles(edges):
            problems.append(Problem("error", "cycle", label, " -> ".join(cycle)))
    return problems


def _edges(bundle: Bundle, slot: str, collection: str, field: str) -> dict[str, list[str]]:
    document = bundle.documents.get(slot) or {}
    edges: dict[str, list[str]] = {}
    for item in document.get(collection, []) or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            edges[item["id"]] = _values(item, field)
    return edges


def check_bundle(
    bundle: Bundle, nodes: dict[str, Node], required: tuple[str, ...] = DOCUMENT_KINDS
) -> list[Problem]:
    """Every referential-integrity check, in reporting order.

    `required` names the document slots this bundle owes; see `check_headers`.
    """
    return [
        *check_headers(bundle, required),
        *check_identifiers(bundle),
        *check_references(bundle, nodes),
        *check_ledger_chain(bundle),
        *check_autonomy_tier(bundle),
        *check_check_references(bundle, nodes),
        *check_acyclic(bundle),
    ]
