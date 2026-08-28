"""Arm C — the ablation: typed intent, plain-text edits.

Identical to the full IR arm in every respect but one: the agent is not asked to
state its change as addressed operations, and edits the source directly. The arm
exists to separate what typing the *intent* buys from what structuring the
*edits* buys — the second is already established, and without this arm the
result would not distinguish them.
"""

from pathlib import Path

from pipelines.common.changerequests import ChangeRequest
from pipelines.lcir import finalise as finaliser
from pipelines.lcir.arm import OBSERVATIONS, PRESENTATION
from pipelines.lcir.arm import Arm as FullArm


class Arm(FullArm):
    name = "lcir_no_ast"
    templates = (PRESENTATION, OBSERVATIONS)
    editing = (
        "Edit the source however you see fit. Read the build and test output for "
        "feedback on what you have done."
    )

    def presentation(self, request: ChangeRequest, workspace: Path) -> str:
        """The same typed IR bundle, with no plan to write."""
        brief = request.brief()
        directory = self.artifact_directory(workspace).relative_to(workspace)
        return PRESENTATION.format(
            identifier=brief["id"],
            title=brief["title"],
            directory=directory,
            observations=self.observations_note(request, workspace),
        )

    def finalise(
        self, request: ChangeRequest, workspace: Path, cell: Path, verification: dict
    ) -> dict:
        return finaliser.finalise(request, workspace, cell, verification, plan_expected=False)
