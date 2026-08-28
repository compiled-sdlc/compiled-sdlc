"""Reading bundles and single documents off disk."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from lcir.model import DOCUMENT_KINDS, NODE_COLLECTIONS, Node, Problem

MANIFEST_NAME = "bundle.json"


class BundleError(Exception):
    """A bundle could not be read at all."""


@dataclass
class Bundle:
    """One change request expressed as five documents plus their manifest."""

    directory: Path
    manifest: dict
    documents: dict[str, dict] = field(default_factory=dict)
    sources: dict[str, Path] = field(default_factory=dict)

    @property
    def change_request(self) -> str:
        return self.manifest.get("change_request", "")

    def nodes(self) -> dict[str, Node]:
        """Every addressable node in the bundle, keyed by identifier.

        Duplicates are reported by the integrity checks; here the first wins.
        """
        found: dict[str, Node] = {}
        for slot, document in self.documents.items():
            for collection, kind in NODE_COLLECTIONS.get(slot, {}).items():
                for item in document.get(collection, []) or []:
                    if not isinstance(item, dict):
                        continue
                    identifier = item.get("id")
                    if isinstance(identifier, str) and identifier not in found:
                        found[identifier] = Node(identifier, kind, slot, collection, item)
        return found

    def duplicate_ids(self) -> list[tuple[str, str]]:
        """Identifiers that appear more than once, with the location of each repeat."""
        seen: set[str] = set()
        repeats: list[tuple[str, str]] = []
        for slot, document in self.documents.items():
            for collection in NODE_COLLECTIONS.get(slot, {}):
                for index, item in enumerate(document.get(collection, []) or []):
                    if not isinstance(item, dict):
                        continue
                    identifier = item.get("id")
                    if not isinstance(identifier, str):
                        continue
                    if identifier in seen:
                        repeats.append((identifier, f"{slot}.{collection}[{index}]"))
                    seen.add(identifier)
        return repeats


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise BundleError(f"{path}: no such file") from exc
    except json.JSONDecodeError as exc:
        raise BundleError(f"{path}: not valid JSON: {exc}") from exc


def load_document(path: Path) -> tuple[str, dict]:
    """Read a single IR document and report which schema it declares itself to be."""
    document = read_json(path)
    kind = document.get("kind")
    if kind == "lifecycle_ir_bundle":
        return "bundle", document
    if kind not in DOCUMENT_KINDS:
        raise BundleError(f"{path}: unknown document kind {kind!r}")
    return DOCUMENT_KINDS[kind], document


def load_bundle(directory: Path) -> tuple[Bundle, list[Problem]]:
    """Read a bundle directory. Documents that cannot be read are reported, not raised."""
    manifest_path = directory / MANIFEST_NAME
    if not manifest_path.exists():
        raise BundleError(f"{directory}: no {MANIFEST_NAME}")
    manifest = read_json(manifest_path)
    bundle = Bundle(directory=directory, manifest=manifest)
    problems: list[Problem] = []
    for slot in DOCUMENT_KINDS:
        relative = manifest.get("documents", {}).get(slot)
        if not isinstance(relative, str):
            continue
        path = directory / relative
        try:
            bundle.documents[slot] = read_json(path)
            bundle.sources[slot] = path
        except BundleError as exc:
            problems.append(
                Problem(
                    "error", "bundle-document", f"{MANIFEST_NAME}#/documents/{slot}", str(exc)
                )
            )
    return bundle, problems
