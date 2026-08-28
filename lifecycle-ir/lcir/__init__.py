"""Loading, schema validation and referential-integrity checking for Lifecycle IR bundles."""

from lcir.bundle import Bundle, load_bundle, load_document
from lcir.model import DOCUMENT_KINDS, NODE_COLLECTIONS, REFERENCES, Problem, Reference

__all__ = [
    "DOCUMENT_KINDS",
    "NODE_COLLECTIONS",
    "REFERENCES",
    "Bundle",
    "Problem",
    "Reference",
    "load_bundle",
    "load_document",
]
