"""Command line entry point for the Lifecycle IR validator."""

import argparse
import json
import sys
from pathlib import Path

from lcir import coverage as coverage_module
from lcir.bundle import Bundle, BundleError, load_bundle, load_document
from lcir.integrity import check_bundle
from lcir.model import Problem
from lcir.schemas import check_schema_set, validate_document

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
EXPECTATIONS = EXAMPLES / "invalid" / "expectations.json"


def _errors(problems: list[Problem]) -> list[Problem]:
    return [problem for problem in problems if problem.severity == "error"]


def _print(problems: list[Problem], indent: str = "  ") -> None:
    for problem in problems:
        print(f"{indent}{problem}")


def validate_bundle_at(directory: Path) -> tuple[Bundle | None, list[Problem]]:
    """Schema-validate every document in a bundle, then check the links between them."""
    try:
        bundle, problems = load_bundle(directory)
    except BundleError as exc:
        return None, [Problem("error", "bundle", str(directory), str(exc))]

    problems = list(problems)
    problems += validate_document(bundle.manifest, "bundle", "bundle.json")
    for slot, document in bundle.documents.items():
        schema_name = slot.replace("_", "-")
        problems += validate_document(document, schema_name, bundle.sources[slot].name)

    nodes = bundle.nodes()
    problems += check_bundle(bundle, nodes)
    _, warnings = coverage_module.measure(bundle, nodes)
    problems += warnings
    return bundle, problems


def validate_path(path: Path) -> list[Problem]:
    """Validate a bundle directory or a single IR document."""
    if path.is_dir():
        return validate_bundle_at(path)[1]
    try:
        schema_name, document = load_document(path)
    except BundleError as exc:
        return [Problem("error", "document", str(path), str(exc))]
    return validate_document(document, schema_name, path.name)


def command_validate(args: argparse.Namespace) -> int:
    status = 0
    for raw in args.paths:
        path = Path(raw)
        problems = validate_path(path)
        errors = _errors(problems)
        warnings = [problem for problem in problems if problem.severity == "warning"]
        if errors or (warnings and args.strict):
            print(f"FAIL  {path}")
            status = 1
        else:
            print(f"ok    {path}")
        _print(errors)
        if args.strict or args.warnings:
            _print(warnings)
    return status


def command_report(args: argparse.Namespace) -> int:
    directory = Path(args.path)
    bundle, problems = validate_bundle_at(directory)
    if bundle is None:
        _print(_errors(problems))
        return 1
    measured, _ = coverage_module.measure(bundle, bundle.nodes())
    print(f"{bundle.change_request}  {bundle.manifest.get('title', '')}")
    print(coverage_module.format_report(measured))
    errors = _errors(problems)
    if errors:
        print(f"\n{len(errors)} integrity error(s)")
        _print(errors)
        return 1
    return 0


def _example_bundles() -> list[Path]:
    root = EXAMPLES / "change-request"
    return sorted(path.parent for path in root.glob("*/bundle.json")) if root.exists() else []


def command_examples(args: argparse.Namespace) -> int:
    """Validate the whole example suite: the schemas, then every example against them."""
    status = 0

    schema_problems = check_schema_set()
    print("ok    schema set" if not schema_problems else "FAIL  schema set")
    _print(schema_problems)
    status |= 1 if schema_problems else 0

    for path in sorted((EXAMPLES / "valid").glob("*.json")):
        problems = _errors(validate_path(path))
        if problems:
            print(f"FAIL  valid/{path.name}")
            _print(problems)
            status = 1
        else:
            print(f"ok    valid/{path.name}")

    expectations = json.loads(EXPECTATIONS.read_text()) if EXPECTATIONS.exists() else {}
    invalid = sorted((EXAMPLES / "invalid").glob("*.json"))
    for path in invalid:
        if path.name == EXPECTATIONS.name:
            continue
        expectation = expectations.get(path.name)
        problems = _errors(validate_path(path))
        if expectation is None:
            print(f"FAIL  invalid/{path.name}")
            print(f"  error: [expectations] {path.name}: not listed in expectations.json")
            status = 1
            continue
        if not problems:
            print(f"FAIL  invalid/{path.name}")
            print("  error: [expectations] the example validated, but must not")
            status = 1
            continue
        expected = expectation.get("message_contains", "")
        if expected and not any(expected in problem.message for problem in problems):
            print(f"FAIL  invalid/{path.name}")
            print(f"  error: [expectations] no reported problem mentions {expected!r}")
            _print(problems)
            status = 1
            continue
        print(f"ok    invalid/{path.name}  ({expectation.get('violates', 'rejected')})")

    unexpected = expectations.keys() - {path.name for path in invalid}
    for name in sorted(unexpected):
        print(f"FAIL  invalid/{name}")
        print("  error: [expectations] listed in expectations.json but absent from examples")
        status = 1

    for directory in _example_bundles():
        problems = validate_bundle_at(directory)[1]
        blocking = problems if args.strict else _errors(problems)
        if blocking:
            print(f"FAIL  change-request/{directory.name}")
            _print(blocking)
            status = 1
        else:
            print(f"ok    change-request/{directory.name}")

    print("\nexamples passed" if status == 0 else "\nexamples failed")
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lifecycle-ir",
        description="Validate Lifecycle IR documents and bundles.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate", help="validate a bundle directory or a single IR document"
    )
    validate.add_argument("paths", nargs="+", help="bundle directories or document files")
    validate.add_argument(
        "--strict", action="store_true", help="treat traceability warnings as failures"
    )
    validate.add_argument("--warnings", action="store_true", help="print warnings without failing")
    validate.set_defaults(func=command_validate)

    report = subparsers.add_parser("report", help="print the traceability report for a bundle")
    report.add_argument("path", help="bundle directory")
    report.set_defaults(func=command_report)

    examples = subparsers.add_parser(
        "examples", help="validate every example shipped with the schemas"
    )
    examples.add_argument(
        "--strict",
        action="store_true",
        default=True,
        help="treat traceability warnings in example bundles as failures (default)",
    )
    examples.add_argument(
        "--no-strict", dest="strict", action="store_false", help="allow traceability warnings"
    )
    examples.set_defaults(func=command_examples)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
