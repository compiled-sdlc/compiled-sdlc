"""Turn the evaluation's output into LaTeX macros the manuscript uses.

The manuscript must not contain a hand-typed measurement. Every figure it
quotes is defined here as a macro, generated from the summary `make eval`
writes and from the lock files the experiment is pinned to. If a number is not
in one of those, there is no macro for it, and the manuscript cannot state it.

A run set that has not met the experiment's discipline is marked as a pilot in
the macros themselves, so a table drawn from it carries the label whether or
not the author remembered to add one.

    python -m eval.manuscript_numbers --output manuscript/generated/numbers.tex
"""

import argparse
import json
from pathlib import Path

from eval import records as records_module
from pipelines.common import locks
from pipelines.common.changerequests import CHANGE_REQUEST_DIR

DEFAULT_OUTPUT = locks.REPO_ROOT / "manuscript" / "generated" / "numbers.tex"

HEADER = """\
% Written by `make manuscript` from data/eval-summary.json and the lock files.
% Do not edit: every number here is rewritten on each build, and a number that
% is not here is one the evaluation did not produce.
"""

# LaTeX macro names cannot carry digits or underscores, so arm names are spelled.
ARM_MACRO = {
    "baseline": "Baseline",
    "lcir": "Lcir",
    "lcir_no_ast": "LcirNoAst",
    "compressed": "Compressed",
}
COMPONENT_MACRO = {
    "plan_validity": "PlanValidity",
    "bundle_assembly": "BundleAssembly",
    "tier_approval": "TierApproval",
    "evidence_path": "EvidencePath",
    "provenance": "Provenance",
}


def macro(name: str, value: str) -> str:
    return f"\\newcommand{{\\{name}}}{{{value}}}"


def money(value: float | None) -> str:
    return "\\todo{not measured}" if value is None else f"{value:.4f}"


def whole(value: float | None) -> str:
    return "\\todo{not measured}" if value is None else f"{value:,.0f}".replace(",", "\\,")


def fraction(value: float | None, state: str = "") -> str:
    if value is None:
        return {"not recorded": "not recorded", "not observable": "not observable"}.get(
            state, "\\todo{not measured}"
        )
    return f"{value:.2f}"


def build(summary: dict) -> list[str]:
    """Every macro the manuscript may use."""
    lines = [HEADER]

    executor = locks.executor()
    target = locks.target()
    environment = locks.read_lock(locks.REPO_ROOT / "bench" / "environment.lock")
    change_requests = len(list(CHANGE_REQUEST_DIR.glob("CR-*.yaml")))

    lines += [
        "% --- what the experiment is pinned to ---",
        macro("pinTarget", target["target"]["name"].replace("_", "\\_")),
        macro("pinCommit", target["target"]["commit"][:12]),
        macro("pinDate", target["target"]["commit_date"][:10]),
        macro("pinModel", executor["model"]["id"]),
        macro("pinExecutorVersion", executor["cli"]["version"]),
        macro("pinJdk", str(environment["toolchain"]["jdk_major"])),
        macro("pinServices", str(len(environment["services"]))),
        macro("pricesCaptured", summary["pricing_captured_on"]),
        macro("budgetTurns", str(executor["budget"]["max_turns"])),
        macro("budgetWallClock", str(int(executor["budget"]["wall_clock_seconds"]))),
        macro("budgetCost", f"{executor['budget']['max_cost_usd']:.2f}"),
        macro("changeRequestCount", str(change_requests)),
        "",
        "% --- the run set these numbers come from ---",
        macro("runLabel", "PILOT" if summary["is_pilot"] else "full run"),
        macro("runIsPilot", "true" if summary["is_pilot"] else "false"),
        macro("runCells", str(summary["cells"])),
        macro("runCounted", str(summary["counted"])),
        macro("runExcluded", str(summary["excluded"])),
        macro("runSeeds", str(summary["seeds"])),
        macro("runChangeRequests", str(len(summary["change_requests"]))),
        macro("runArms", str(len(summary["arms"]))),
        macro("runFrontier", ", ".join(summary["pareto_frontier"]).replace("_", "\\_")),
        "",
        "% --- success-adjusted lifecycle cost, per arm ---",
    ]

    total_spend = 0.0
    for entry in summary["salc"]:
        name = ARM_MACRO.get(entry["arm"])
        if name is None:
            continue
        total_spend += entry["total_cost_usd"]
        spread = entry["distributions"]
        lines += [
            macro(f"salc{name}", money(entry["salc_usd_per_verified"])),
            macro(f"verified{name}", str(entry["verified"])),
            macro(f"cells{name}", str(entry["cells_counted"])),
            macro(f"successRate{name}", f"{entry['success_rate'] * 100:.0f}"),
            macro(f"cost{name}", money(spread["cost_usd"]["median"])),
            macro(f"costIqrLow{name}", money(spread["cost_usd"]["q1"])),
            macro(f"costIqrHigh{name}", money(spread["cost_usd"]["q3"])),
            macro(f"tokens{name}", whole(spread["total_tokens"]["median"])),
            macro(f"reasoning{name}", whole(spread["reasoning_tokens"]["median"])),
            macro(f"turns{name}", whole(spread["turns"]["median"])),
            macro(f"wall{name}", whole(spread["wall_time_seconds"]["median"])),
            macro(f"spread{name}", f"{spread['cost_usd']['spread']:.1f}"),
        ]
    lines.append(macro("runTotalSpend", f"{total_spend:.2f}"))

    lines += ["", "% --- governance completeness, per arm and component ---"]
    for index in summary["governance"]:
        name = ARM_MACRO.get(index["arm"])
        if name is None:
            continue
        lines.append(
            macro(
                f"gci{name}",
                "not observable" if index["index"] is None else f"{index['index']:.2f}",
            )
        )
        for component in index["components"]:
            suffix = COMPONENT_MACRO.get(component["component"])
            if suffix is None:
                continue
            lines.append(
                macro(f"gci{name}{suffix}", fraction(component["value"], component["state"]))
            )

    lines += [
        "",
        "% --- the ratio the pilot's cost profile turns on ---",
        macro(
            "irPremium",
            _ratio(summary, "lcir", "baseline"),
        ),
        macro(
            "ablationPremium",
            _ratio(summary, "lcir_no_ast", "baseline"),
        ),
    ]
    return lines


def _ratio(summary: dict, arm: str, against: str) -> str:
    """One arm's median cost as a multiple of another's."""
    costs = {
        entry["arm"]: entry["distributions"]["cost_usd"]["median"] for entry in summary["salc"]
    }
    if arm not in costs or against not in costs or not costs[against]:
        return "\\todo{not measured}"
    return f"{costs[arm] / costs[against]:.1f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=Path("data") / "eval-summary.json")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)

    if not arguments.summary.exists():
        print(f"no evaluation summary at {arguments.summary}; run make eval first")
        return 1
    summary = json.loads(arguments.summary.read_text())
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text("\n".join(build(summary)) + "\n")
    label = records_module.PILOT_LABEL if summary["is_pilot"] else records_module.FULL_LABEL
    print(f"wrote {arguments.output} from {arguments.summary} ({label})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
