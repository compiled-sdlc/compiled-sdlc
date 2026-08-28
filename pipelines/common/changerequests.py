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
EVIDENCE_DIR = locks.REPO_ROOT / "bench" / "evidence"
SCHEMA_PATH = locks.REPO_ROOT / "bench" / "change-request.schema.json"

# The only fields an arm may put in front of an agent.
BRIEF_FIELDS = (
    "id",
    "title",
    "category",
    "modules",
    "statement",
    "context",
    "behaviours",
    "boundaries",
    "evidence",
)

CATEGORIES = ("feature", "bug_fix", "non_functional", "incident")

# What makes a change request hard. The pilot scored every arm at every request,
# so a set of single-endpoint changes cannot separate arms on success; these are
# the shapes the full set is built from instead.
DIFFICULTIES = (
    "single_endpoint",
    "cross_service",
    "misleading_obvious_fix",
    "invariant_tripping_nfr",
    "live_stack_incident",
    "refactor_under_constraint",
)


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
class Behaviour:
    """One observable outcome that settles the request. Visible to every arm."""

    id: str
    statement: str


@dataclass(frozen=True)
class Boundary:
    """A boundary the request states openly. Not the hidden invariant that scores it."""

    id: str
    category: str
    obligation: str
    statement: str


@dataclass(frozen=True)
class EvidenceArtifact:
    """One thing that was observed, and where it lives."""

    id: str
    kind: str
    path: Path
    caption: str

    def read(self) -> str:
        return self.path.read_text()


@dataclass(frozen=True)
class Evidence:
    """What was observed of the running application, carried in as input.

    Unlike the acceptance checks, this is not ground truth and is not hidden:
    every arm renders it and the agent reads it. It is what makes an incident
    change request an account of something that happened rather than an
    assertion that it did.
    """

    captured_on: str
    summary: str
    artifacts: tuple[EvidenceArtifact, ...]


@dataclass(frozen=True)
class AcceptanceCheck:
    """A hidden test, the module it runs in, and where the harness puts it."""

    id: str
    module: str
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
    modules: tuple[str, ...]
    risk_class: str
    statement: str
    context: str
    needs_stack: bool
    difficulty: str
    difficulty_rationale: str
    behaviours: tuple[Behaviour, ...]
    boundaries: tuple[Boundary, ...]
    must_invariants: tuple[Invariant, ...]
    acceptance: tuple[AcceptanceCheck, ...]
    path: Path
    evidence: Evidence | None = None

    @property
    def module(self) -> str:
        """The module the change principally belongs to."""
        return self.modules[0]

    @property
    def module_path(self) -> str:
        return locks.module_path(self.module)

    @property
    def module_paths(self) -> tuple[str, ...]:
        """Every module the change may touch, in the order the request names them."""
        return tuple(locks.module_path(module) for module in self.modules)

    def checks_for(self, module: str) -> tuple["AcceptanceCheck", ...]:
        return tuple(check for check in self.acceptance if check.module == module)

    def brief(self) -> dict:
        """The agent's view: the work, and nothing that decides the work."""
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "modules": list(self.module_paths),
            "statement": self.statement.strip(),
            "context": self.context.strip(),
            "behaviours": [
                {"id": item.id, "statement": item.statement} for item in self.behaviours
            ],
            "boundaries": [
                {
                    "id": item.id,
                    "category": item.category,
                    "obligation": item.obligation,
                    "statement": item.statement,
                }
                for item in self.boundaries
            ],
            "evidence": self.evidence_brief(),
        }

    def evidence_brief(self) -> dict | None:
        """What was observed, as the arms are given it. The same content in each."""
        if self.evidence is None:
            return None
        return {
            "captured_on": self.evidence.captured_on,
            "summary": self.evidence.summary.strip(),
            "artifacts": [
                {"id": item.id, "kind": item.kind, "caption": item.caption, "name": item.path.name}
                for item in self.evidence.artifacts
            ],
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
        modules=tuple(document["modules"]),
        difficulty=document["difficulty"],
        difficulty_rationale=document["difficulty_rationale"],
        risk_class=document["risk_class"],
        statement=document["statement"],
        context=document.get("context", ""),
        needs_stack=bool(document.get("needs_stack", False)),
        behaviours=tuple(
            Behaviour(id=item["id"], statement=item["statement"]) for item in document["behaviours"]
        ),
        boundaries=tuple(
            Boundary(
                id=item["id"],
                category=item["category"],
                obligation=item["obligation"],
                statement=item["statement"],
            )
            for item in document.get("boundaries", ())
        ),
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
                module=item["module"],
                source=locks.REPO_ROOT / item["source"],
                destination=item["destination"],
                test_class=item["test_class"],
                statement=item.get("statement", ""),
            )
            for item in document["acceptance"]
        ),
        path=path,
        evidence=parse_evidence(document.get("evidence")),
    )


def parse_evidence(document: dict | None) -> Evidence | None:
    if not document:
        return None
    return Evidence(
        captured_on=document["captured_on"],
        summary=document["summary"],
        artifacts=tuple(
            EvidenceArtifact(
                id=item["id"],
                kind=item["kind"],
                path=locks.REPO_ROOT / item["path"],
                caption=item["caption"],
            )
            for item in document["artifacts"]
        ),
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
            module_paths = {module: locks.module_path(module) for module in request.modules}
        except KeyError as error:
            problems.append(f"{request.id}: {error}")
            continue
        for check in request.acceptance:
            if check.module not in module_paths:
                named = ", ".join(sorted(module_paths))
                problems.append(
                    f"{request.id}: {check.id} runs in {check.module}, which the request "
                    f"does not name (it names {named})"
                )
                continue
            if not check.source.exists():
                problems.append(f"{request.id}: {check.id} has no test at {check.source}")
            elif check.simple_class_name not in check.source.read_text():
                problems.append(f"{request.id}: {check.source.name} does not define its test class")
            if not check.destination.startswith(module_paths[check.module]):
                problems.append(
                    f"{request.id}: {check.id} lands outside {module_paths[check.module]}"
                )
        for module in request.modules:
            if not any(check.module == module for check in request.acceptance):
                problems.append(
                    f"{request.id}: names module {module} but no hidden check runs there"
                )
        problems.extend(evidence_problems(request))
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


def evidence_problems(request: ChangeRequest) -> list[str]:
    """Whether a request's evidence is really there and really from this pin.

    The schema already insists an incident carries evidence. What it cannot see
    is whether the files exist, and whether they were captured against the
    commit the experiment is pinned to --- evidence from another version of the
    application would describe behaviour the agent is not looking at.
    """
    problems: list[str] = []
    if request.evidence is None:
        return problems
    pin = locks.target()["target"]["commit"]
    for artifact in request.evidence.artifacts:
        if not artifact.path.exists():
            problems.append(f"{request.id}: {artifact.id} has no artifact at {artifact.path}")
    capture = EVIDENCE_DIR / request.id / "capture.json"
    if not capture.exists():
        problems.append(
            f"{request.id}: no capture record at {capture}; evidence is captured by "
            f"infra/capture_evidence.py, not written by hand"
        )
        return problems
    recorded = json.loads(capture.read_text())
    if recorded.get("pin_commit") != pin:
        problems.append(
            f"{request.id}: evidence was captured against {recorded.get('pin_commit')}, "
            f"not the pinned {pin}"
        )
    if recorded.get("captured_on") != request.evidence.captured_on:
        problems.append(
            f"{request.id}: says the evidence was captured on "
            f"{request.evidence.captured_on}, the capture record says "
            f"{recorded.get('captured_on')}"
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
            f"ok    {request.id}  {request.category:15s} {request.difficulty:24s}"
            f"  {'+'.join(request.modules):18s}"
            f"  {len(request.must_invariants)} inv"
            f"  {len(request.acceptance)} check(s)"
            f"{'  live stack' if request.needs_stack else ''}"
        )
    print("\nchange-request set is consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
