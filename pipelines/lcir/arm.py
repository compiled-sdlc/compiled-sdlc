"""Arm B — the full Lifecycle IR.

The change request reaches the agent as typed intent and typed constraints, not
as prose, and the agent is asked to state its change as addressed operations
before making it. After the run the harness writes what verification observed
into an evidence graph, records who did what in a provenance ledger, assembles
the whole bundle, validates it, and renders the projections a human would read.

The bundle the agent sees carries no ground truth: its acceptance conditions
name checks derived from the change request's own behaviours, never the hidden
checks that score the run.
"""

import json
import shutil
from pathlib import Path

from pipelines.common import locks
from pipelines.common.arms import BaseArm
from pipelines.common.changerequests import ChangeRequest
from pipelines.lcir import compile as compiler
from pipelines.lcir import finalise as finaliser

SCHEMA_NAMES = ("common", "intent-graph", "constraint-graph", "transformation-plan")

PRESENTATION = """\
The change request, {identifier} — {title} — is given to you as a Lifecycle IR
bundle in {directory}:

- intent-graph.json — the goal, the behaviours that realise it, and the
  acceptance condition that settles each behaviour.
- constraint-graph.json — the boundaries the change is bounded by, each with an
  obligation and a severity, and the risk class of the change.
- schemas/ — the schema each document conforms to.
{observations}
Read the bundle. It is the specification; there is no prose version of it.
"""

OBSERVATIONS = """\
The intent graph carries observations: what was seen of the running system,
each naming the recorded artifact it stands on, under {directory}/evidence/.
"""

PLAN_INSTRUCTION = """\
Before you edit anything, write {directory}/transformation-plan.json: the
change stated as addressed operations, conforming to
{directory}/schemas/transformation-plan.schema.json.

Address each code change either by an OpenRewrite recipe or by a tree-sitter
node query naming the syntax node it applies to — a file and a node, not a line
range. Each code change states which acceptance condition or behaviour it
implements, and the constraints it respects. Then apply the plan you wrote.
"""


class Arm(BaseArm):
    name = "lcir"
    templates = (PRESENTATION, OBSERVATIONS, PLAN_INSTRUCTION)
    editing = (
        "Make each edit as the operation your transformation plan addresses, and keep "
        "the plan and the source in step. Read the build and test output for feedback."
    )

    def prepare(self, request: ChangeRequest, workspace: Path) -> dict:
        """Write the typed bundle, the evidence it stands on, and the schemas."""
        evidence = self.place_evidence(request, workspace)
        addressed = {
            artifact.id: relative
            for relative, artifact in self.evidence_entries(request, workspace)
        }
        placed = [
            *evidence,
            *(
                self.write(workspace, name, json.dumps(document, indent=2) + "\n")
                for name, document in compiler.documents(request, addressed).items()
            ),
        ]
        schemas = self.artifact_directory(workspace) / "schemas"
        schemas.mkdir(parents=True, exist_ok=True)
        for name in SCHEMA_NAMES:
            source = locks.REPO_ROOT / "lifecycle-ir" / "schemas" / f"{name}.schema.json"
            shutil.copy(source, schemas / source.name)
            placed.append(str((schemas / source.name).relative_to(workspace)))
        return {"artifacts": placed}

    def presentation(self, request: ChangeRequest, workspace: Path) -> str:
        """A typed IR bundle in the workspace, plus a plan the agent must write."""
        brief = request.brief()
        directory = self.artifact_directory(workspace).relative_to(workspace)
        return (
            PRESENTATION.format(
                identifier=brief["id"],
                title=brief["title"],
                directory=directory,
                observations=self.observations_note(request, workspace),
            )
            + "\n"
            + PLAN_INSTRUCTION.format(directory=directory)
        )

    def observations_note(self, request: ChangeRequest, workspace: Path) -> str:
        """A line pointing at the observations, for a request that has any."""
        if request.evidence is None:
            return ""
        directory = self.artifact_directory(workspace).relative_to(workspace)
        return OBSERVATIONS.format(directory=directory)

    def finalise(
        self, request: ChangeRequest, workspace: Path, cell: Path, verification: dict
    ) -> dict:
        return finaliser.finalise(request, workspace, cell, verification, plan_expected=True)
