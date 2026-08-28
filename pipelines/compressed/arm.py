"""Arm D — aggressively compressed artifacts.

The same change request, minified: single-line JSON with abbreviated keys, no
whitespace, no explanation, and an instruction as terse as it can be made. This
is the token-minimising strawman — the arm that spends the fewest tokens on
input and, if the compression literature holds, pays for it in output and in
retries.

It carries exactly the same content as the other arms. Only the presentation is
squeezed.
"""

import json
from pathlib import Path

from pipelines.common.arms import BaseArm
from pipelines.common.changerequests import ChangeRequest

KEYS = {"id": "i", "title": "t", "statement": "s", "behaviours": "b", "boundaries": "x"}


def minify(request: ChangeRequest) -> str:
    """The brief with its keys abbreviated, its prose stripped, and no whitespace."""
    brief = request.brief()
    payload = {
        KEYS["id"]: brief["id"],
        KEYS["title"]: brief["title"],
        KEYS["statement"]: " ".join(brief["statement"].split()),
        KEYS["behaviours"]: [item["statement"] for item in brief["behaviours"]],
        KEYS["boundaries"]: [
            f"{item['obligation']}:{item['statement']}" for item in brief["boundaries"]
        ],
    }
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


class Arm(BaseArm):
    name = "compressed"
    editing = "Edit as needed. Build output is your feedback."

    def prepare(self, request: ChangeRequest, workspace: Path) -> dict:
        return {"artifacts": [self.write(workspace, "cr.json", minify(request) + "\n")]}

    def presentation(self, request: ChangeRequest, workspace: Path) -> str:
        """One minified line in the prompt: i=id, t=title, s=statement, b=behaviours, x=bounds."""
        return f"CR (i id,t title,s statement,b required,x bounds):\n{minify(request)}"
