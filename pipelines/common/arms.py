"""What every arm shares, so that only the representation differs.

An arm's whole job is to render one change request into artifacts and put a task
in front of the agent. Everything else about a run — the model, the tool set,
the three budgets, the workspace, the verification, the record — is fixed by the
harness and identical across arms. That is the experimental control: if two arms
differ in their cost, the representation is the only thing that can explain it.

The task framing below is shared verbatim. Each arm supplies only the section
that presents the change request, and the sentence that tells the agent how it
is expected to edit. Anything an arm wants to add has to be added to all four.

Prompt tuning is bounded and logged. Each arm gets the same allowance of
revisions to its template, recorded in bench/prompt-allowance.json with the
digest of the frozen template; a test holds the allowances equal. Without that,
the arm someone spent an afternoon on would win on effort rather than on
representation.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pipelines.common import locks
from pipelines.common.changerequests import ChangeRequest
from pipelines.common.workspace import ARTIFACT_DIRECTORY

ALLOWANCE_LEDGER = locks.REPO_ROOT / "bench" / "prompt-allowance.json"

__all__ = ["ARTIFACT_DIRECTORY", "Allowance", "BaseArm", "allowances", "digest"]

TASK_FRAMING = """\
You are working in a checkout of the {application} project. Your task concerns
the module at {module}.

{presentation}

How to work:
- Make the change in {module}. Do not change any other module.
- Build and test the module with:
      ./mvnw --batch-mode -pl {module} -am test
  The JDK is already configured for this shell.
- {editing}
- The module's existing tests must still pass when you are done.
- Stop when the change is complete. Do not commit, and do not push.
"""


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Allowance:
    """One arm's prompt-iteration budget and what it has spent."""

    arm: str
    allowance: int
    iterations_used: int
    template_sha256: str
    frozen_on: str


def allowances(path: Path | None = None) -> dict[str, Allowance]:
    """The recorded allowance for each arm."""
    ledger = json.loads((path or ALLOWANCE_LEDGER).read_text())
    return {arm: Allowance(arm=arm, **entry) for arm, entry in sorted(ledger["arms"].items())}


class BaseArm:
    """The shared half of an arm."""

    name: str = ""
    #: The one sentence that tells the agent how it is expected to edit.
    editing: str = ""

    def presentation(self, request: ChangeRequest, workspace: Path) -> str:
        """How this arm puts the change request in front of the agent."""
        raise NotImplementedError

    def prepare(self, request: ChangeRequest, workspace: Path) -> dict:
        """Place this arm's artifacts in the workspace. Returns what it placed."""
        return {"artifacts": []}

    def artifact_directory(self, workspace: Path) -> Path:
        directory = workspace / ARTIFACT_DIRECTORY
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def write(self, workspace: Path, name: str, content: str) -> str:
        """Write one artifact into the workspace and report its relative path."""
        path = self.artifact_directory(workspace) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return str(path.relative_to(workspace))

    def prompt(self, request: ChangeRequest, workspace: Path) -> str:
        """The instruction the agent is given. Built from the brief, never the ground truth."""
        return TASK_FRAMING.format(
            application=locks.target()["target"]["name"],
            module=request.module_path,
            presentation=self.presentation(request, workspace).strip(),
            editing=self.editing.strip(),
        )

    def template_digest(self) -> str:
        """A digest of everything about this arm that shapes a prompt."""
        return digest(TASK_FRAMING + self.editing + type(self).presentation.__doc__ or "")

    def finalise(
        self, request: ChangeRequest, workspace: Path, cell: Path, verification: dict
    ) -> dict:
        """What the arm does with the run once the harness has verified it."""
        return {}
