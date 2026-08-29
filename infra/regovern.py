#!/usr/bin/env python3
"""Recompute a run's governance figures from the bundle it left behind.

A change to the validator or the coverage rules changes what a governance
figure *means*. Figures taken under the old definition cannot be averaged with
figures taken under the new one, so the evaluation sets the old ones aside
(`governance_revision` on the record says which definition it was scored
under). This puts them back, where the bundle is still on disk to be re-read.

It touches only the governance figures. Cost, tokens, turns, timings and the
verification outcome are measurements of the run itself and are never rewritten
— the point is to re-derive a judgement, not to re-state an observation. Every
record it rewrites keeps a note of what it was before.

    python infra/regovern.py [--runs runs/] [--dry-run]

A run whose bundle is gone cannot be recomputed. It keeps its old revision and
stays set aside, which is the honest outcome: the figures are not comparable and
nothing on disk can make them so.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lifecycle-ir"))

from lcir.bundle import DOCUMENT_KINDS, load_bundle  # noqa: E402
from lcir.coverage import measure  # noqa: E402
from lcir.integrity import check_bundle  # noqa: E402
from pipelines.common import locks  # noqa: E402
from pipelines.lcir.finalise import BUNDLE_DIRECTORY, GOVERNANCE_REVISION  # noqa: E402


def recompute(bundle_directory: Path, plan_expected: bool) -> dict:
    """The governance figures this bundle earns under the current definition."""
    bundle, load_problems = load_bundle(bundle_directory)
    problems = [str(problem) for problem in load_problems]
    owed = tuple(slot for slot in DOCUMENT_KINDS if slot != "transformation_plan" or plan_expected)
    problems += [
        str(problem)
        for problem in check_bundle(bundle, bundle.nodes(), owed)
        if problem.severity == "error"
    ]
    coverage, _ = measure(bundle, bundle.nodes())
    has_plan = bundle.documents.get("transformation_plan") is not None
    constraints = bundle.documents.get("constraint_graph") or {}
    tier = (constraints.get("risk") or {}).get("autonomy_tier")
    return {
        "governance_revision": GOVERNANCE_REVISION,
        "bundle_problems": problems[:10],
        "tier_required": tier in {"L2", "L3"},
        "tier_satisfied": not any("tier-approval-missing" in problem for problem in problems),
        "bundle_validated": bool(problems == [] and (not plan_expected or has_plan)),
        "obligations_traced": round(coverage.obligations_traced, 4),
        "transformations_attributed": (
            round(coverage.transformations_attributed, 4)
            if coverage.transformation_total > 0
            else None
        ),
    }


def rewrite(cell: Path, dry_run: bool) -> tuple[str, str]:
    """Bring one cell's figures up to date. Returns an outcome and a note."""
    record_path = cell / "record.json"
    record = json.loads(record_path.read_text())
    artifacts = record.get("arm_artifacts") or {}
    if "transformation_plan" not in artifacts:
        return "skipped", "produces no IR"
    if artifacts.get("governance_revision") == GOVERNANCE_REVISION:
        return "current", "already scored under this definition"

    bundle_directory = cell / BUNDLE_DIRECTORY
    if not (bundle_directory / "bundle.json").exists():
        return "not comparable", f"no bundle kept at {bundle_directory.name}"

    figures = recompute(bundle_directory, bool(artifacts.get("transformation_plan_expected")))
    before = {key: artifacts.get(key) for key in figures}
    if dry_run:
        return "would rewrite", f"{before} -> {figures}"

    record["arm_artifacts"] = {
        **artifacts,
        **figures,
        # What the record said before, so a rewritten figure is never mistaken
        # for an original observation.
        "governance_superseded": {
            "revision": artifacts.get("governance_revision", 1),
            "figures": before,
            "recomputed_from": BUNDLE_DIRECTORY,
        },
    }
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    changed = [key for key in figures if before.get(key) != figures[key]]
    return "rewritten", ("changed " + ", ".join(changed)) if changed else "figures unchanged"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=locks.REPO_ROOT / "runs")
    parser.add_argument("--dry-run", action="store_true")
    arguments = parser.parse_args(argv)

    cells = sorted(path.parent for path in arguments.runs.glob("*/record.json"))
    if not cells:
        print(f"no cells under {arguments.runs}")
        return 1

    counts: dict[str, int] = {}
    for cell in cells:
        outcome, note = rewrite(cell, arguments.dry_run)
        counts[outcome] = counts.get(outcome, 0) + 1
        if outcome not in {"skipped", "current"}:
            print(f"{outcome:15s} {cell.name}  ({note})")
    print()
    for outcome, count in sorted(counts.items()):
        print(f"{count:3d} {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
