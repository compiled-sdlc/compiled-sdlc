"""Change requests: what an agent is asked to do, and what decides whether it did it.

A change request has two halves and they are kept apart on purpose. The
statement is the work, and it is the only part an arm may render for the agent.
The invariants and the acceptance checks are ground truth: they are tracked
openly in bench/, they never enter a prompt or a workspace before a run, and the
harness applies them afterwards.

`ChangeRequest.brief()` builds the agent's view. It is constructed from an
explicit list of fields rather than by removing the hidden ones, so a field
added to the format later is hidden until someone decides otherwise.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from pipelines.common import locks

CHANGE_REQUEST_DIR = locks.REPO_ROOT / "bench" / "change-requests"
CHECKS_DIR = locks.REPO_ROOT / "bench" / "checks"
SCHEMA_PATH = locks.REPO_ROOT / "bench" / "change-request.schema.json"

# The only fields an arm may put in front of an agent.
BRIEF_FIELDS = ("id", "title", "category", "module", "statement", "context")

CATEGORIES = ("feature", "bug_fix", "non_functional", "incident")


@dataclass(frozen=True)
class Invariant:
    """A boundary the change must not cross."""

    id: str
    kind: str
    statement: str
    paths: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    pattern: str = ""


@dataclass(frozen=True)
class AcceptanceCheck:
    """A hidden test, and where the harness puts it to run it."""

    id: str
    source: Path
    destination: str
    test_class: str
    statement: str = ""

    @property
    def simple_class_name(self) -> str:
        return self.test_class.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class ChangeRequest:
    """One unit of work, with the ground truth that settles it."""

    id: str
    title: str
    category: str
    module: str
    risk_class: str
    statement: str
    context: str
    must_invariants: tuple[Invariant, ...]
    acceptance: tuple[AcceptanceCheck, ...]
    path: Path

    @property
    def module_path(self) -> str:
        return locks.module_path(self.module)

    def brief(self) -> dict:
        """The agent's view: the work, and nothing that decides the work."""
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "module": self.module_path,
            "statement": self.statement.strip(),
            "context": self.context.strip(),
        }


@lru_cache(maxsize=1)
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def validate(document: dict) -> list[str]:
    """Schema errors in one change request, as messages."""
    validator = Draft202012Validator(schema())
    return [
        f"{'/'.join(str(part) for part in error.path) or '(root)'}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    ]


def parse(document: dict, path: Path) -> ChangeRequest:
    """Build a change request from a validated document."""
    return ChangeRequest(
        id=document["id"],
        title=document["title"],
        category=document["category"],
        module=document["module"],
        risk_class=document["risk_class"],
        statement=document["statement"],
        context=document.get("context", ""),
        must_invariants=tuple(
            Invariant(
                id=item["id"],
                kind=item["kind"],
                statement=item["statement"],
                paths=tuple(item.get("paths", ())),
                prefixes=tuple(item.get("prefixes", ())),
                pattern=item.get("pattern", ""),
            )
            for item in document["must_invariants"]
        ),
        acceptance=tuple(
            AcceptanceCheck(
                id=item["id"],
                source=locks.REPO_ROOT / item["source"],
                destination=item["destination"],
                test_class=item["test_class"],
                statement=item.get("statement", ""),
            )
            for item in document["acceptance"]
        ),
        path=path,
    )


def load(path: Path) -> ChangeRequest:
    """Read and validate one change request."""
    document = yaml.safe_load(path.read_text())
    problems = validate(document)
    if problems:
        raise ValueError(f"{path.name}: " + "; ".join(problems))
    return parse(document, path)


def load_all(directory: Path | None = None) -> list[ChangeRequest]:
    """Every change request in the set, by identifier."""
    directory = directory or CHANGE_REQUEST_DIR
    return [load(path) for path in sorted(directory.glob("CR-*.yaml"))]


def check_set(directory: Path | None = None) -> list[str]:
    """Problems with the change-request set as a whole."""
    directory = directory or CHANGE_REQUEST_DIR
    problems: list[str] = []
    requests: list[ChangeRequest] = []
    for path in sorted(directory.glob("CR-*.yaml")):
        try:
            requests.append(load(path))
        except ValueError as error:
            problems.append(str(error))
    seen: set[str] = set()
    for request in requests:
        if request.id in seen:
            problems.append(f"{request.id}: declared twice")
        seen.add(request.id)
        if request.path.stem != request.id:
            problems.append(f"{request.path.name}: names {request.id}")
        try:
            module = request.module_path
        except KeyError as error:
            problems.append(f"{request.id}: {error}")
            continue
        for check in request.acceptance:
            if not check.source.exists():
                problems.append(f"{request.id}: {check.id} has no test at {check.source}")
            elif check.simple_class_name not in check.source.read_text():
                problems.append(f"{request.id}: {check.source.name} does not define its test class")
            if not check.destination.startswith(module):
                problems.append(f"{request.id}: {check.id} lands outside {module}")
        checkout = locks.target_checkout()
        if not checkout.exists():
            continue
        for invariant in request.must_invariants:
            for path in (*invariant.paths, *invariant.prefixes):
                if not (checkout / path).exists():
                    problems.append(
                        f"{request.id}: {invariant.id} names {path}, which the pin does not have"
                    )
    return problems


def main() -> int:
    """Report on the change-request set. Used by `make bench-validate`."""
    problems = check_set()
    for problem in problems:
        print(f"error: {problem}")
    if problems:
        print(f"\n{len(problems)} problem(s) in the change-request set")
        return 1
    for request in load_all():
        print(
            f"ok    {request.id}  {request.category:15s} {request.module_path}"
            f"  {len(request.must_invariants)} invariants"
            f"  {len(request.acceptance)} hidden check(s)"
        )
    print("\nchange-request set is consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
