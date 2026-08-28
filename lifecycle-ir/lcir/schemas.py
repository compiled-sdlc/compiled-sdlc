"""Schema loading and per-document validation."""

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from lcir.model import DOCUMENT_KINDS, IR_VERSION, Problem

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
SCHEMA_URI = "urn:compiled-sdlc:lifecycle-ir:{version}:{name}"


def schema_path(name: str) -> Path:
    return SCHEMA_DIR / f"{name}.schema.json"


@lru_cache(maxsize=1)
def load_schemas() -> dict[str, dict]:
    """Every schema document, keyed by its short name."""
    return {
        p.name.removesuffix(".schema.json"): json.loads(p.read_text())
        for p in sorted(SCHEMA_DIR.glob("*.schema.json"))
    }


@lru_cache(maxsize=1)
def registry() -> Registry:
    """A resolver over the local schema set, keyed by each schema's own $id."""
    resources = [
        (schema["$id"], Resource.from_contents(schema)) for schema in load_schemas().values()
    ]
    return Registry().with_resources(resources)


def validator_for(name: str) -> Draft202012Validator:
    """A validator for one schema, with format assertions enabled."""
    schema = load_schemas()[name]
    return Draft202012Validator(
        schema, registry=registry(), format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def check_schema_set() -> list[Problem]:
    """The schema documents themselves: identified, versioned, and self-consistent."""
    problems: list[Problem] = []
    schemas = load_schemas()
    expected_names = {"common", "bundle", *DOCUMENT_KINDS.values()}
    missing = expected_names - schemas.keys()
    for name in sorted(missing):
        problems.append(
            Problem("error", "schema-missing", f"schemas/{name}.schema.json", "schema is absent")
        )

    for name, schema in sorted(schemas.items()):
        location = f"schemas/{name}.schema.json"
        expected_id = SCHEMA_URI.format(version=IR_VERSION.rsplit(".", 1)[0], name=name)
        if schema.get("$id") != expected_id:
            problems.append(
                Problem(
                    "error",
                    "schema-id",
                    location,
                    f"$id is {schema.get('$id')!r}, expected {expected_id!r}",
                )
            )
        if schema.get("version") != IR_VERSION:
            problems.append(
                Problem(
                    "error",
                    "schema-version",
                    location,
                    f"version is {schema.get('version')!r}, expected {IR_VERSION!r}",
                )
            )
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            problems.append(Problem("error", "schema-invalid", location, str(exc)))

    declared = load_schemas().get("common", {}).get("$defs", {}).get("irVersion", {}).get("const")
    if declared != IR_VERSION:
        problems.append(
            Problem(
                "error",
                "schema-version",
                "schemas/common.schema.json",
                f"$defs.irVersion const is {declared!r}, expected {IR_VERSION!r}",
            )
        )
    return problems


def validate_document(document: dict, name: str, location: str) -> list[Problem]:
    """Validate one instance against one schema."""
    problems = []
    for error in sorted(validator_for(name).iter_errors(document), key=lambda e: list(e.path)):
        pointer = "/".join(str(part) for part in error.path)
        where = f"{location}#/{pointer}" if pointer else location
        problems.append(Problem("error", "schema", where, error.message))
    return problems
