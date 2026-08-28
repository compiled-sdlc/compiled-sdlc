"""Arm A — baseline.

The change request as a person would write it and a person would read it:
prose in the prompt, free-form editing, and whatever the build prints as
feedback. Nothing is typed, nothing is addressed, nothing is machine-checkable
before the harness looks at it. This is the arm the other three are measured
against, and it is deliberately the ordinary way of working.
"""

from pathlib import Path

from pipelines.common.arms import BaseArm
from pipelines.common.changerequests import ChangeRequest

REQUIREMENT = """\
The change request, {identifier} — {title}:

{statement}

What the change has to do:

{behaviours}
{boundaries}{evidence}"""

OBSERVED = """
What was observed, on {captured_on}:

{summary}

The files are in the workspace:

{files}
"""


class Arm(BaseArm):
    name = "baseline"
    templates = (REQUIREMENT, OBSERVED)
    editing = (
        "Edit the source however you see fit. Read the build and test output for "
        "feedback on what you have done."
    )

    def prepare(self, request: ChangeRequest, workspace: Path) -> dict:
        return {"artifacts": self.place_evidence(request, workspace)}

    def observed(self, request: ChangeRequest, workspace: Path) -> str:
        """The runtime evidence as prose, the way a ticket would carry it."""
        brief = request.brief()
        if not brief["evidence"]:
            return ""
        files = "\n".join(
            f"- {relative} — {artifact.caption}"
            for relative, artifact in self.evidence_entries(request, workspace)
        )
        return OBSERVED.format(
            captured_on=brief["evidence"]["captured_on"],
            summary=brief["evidence"]["summary"],
            files=files,
        )

    def presentation(self, request: ChangeRequest, workspace: Path) -> str:
        """Prose in the prompt: the requirement as natural-language text."""
        brief = request.brief()
        behaviours = "\n".join(f"- {item['statement']}" for item in brief["behaviours"])
        boundaries = ""
        if brief["boundaries"]:
            stated = "\n".join(f"- {item['statement']}" for item in brief["boundaries"])
            boundaries = f"\nWhat it must not do:\n\n{stated}\n"
        statement = brief["statement"]
        if brief["context"]:
            statement = f"{statement}\n\n{brief['context']}"
        return REQUIREMENT.format(
            identifier=brief["id"],
            title=brief["title"],
            statement=statement,
            behaviours=behaviours,
            boundaries=boundaries,
            evidence=self.observed(request, workspace),
        )
