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

    # Relative interquartile range: the spread as a fraction of the median, which
    # is what makes two arms at different price points comparable on variability.
    for entry in summary["salc"]:
        name = ARM_MACRO.get(entry["arm"])
        spread = entry["distributions"]["cost_usd"]
        median = spread.get("median") or 0.0
        # Older summaries carry the quartiles without the range between them.
        iqr = spread.get("iqr", spread.get("q3", 0.0) - spread.get("q1", 0.0))
        if name and median:
            lines.append(macro(f"relIqr{name}", f"{iqr / median:.2f}"))

    lines += ["", "% --- which differences the run supports ---"]
    for gap in summary.get("cost_gaps", []):
        pair = f"{ARM_MACRO.get(gap['cheaper'], '')}Vs{ARM_MACRO.get(gap['dearer'], '')}"
        if "Vs" in pair and pair != "Vs":
            lines += [
                macro(f"costGap{pair}", money(gap["gap_usd"])),
                macro(f"costRatio{pair}", f"{gap['ratio']:.1f}" if gap["ratio"] else "--"),
                macro(f"costClears{pair}", "true" if gap["clears"] else "false"),
            ]
    success = summary.get("success_gaps", [])
    established = [gap for gap in success if gap["clears"]]
    widest_cells = max((gap["cells"] for gap in success), default=0)
    seed_spread = max((gap["widest_within_arm_spread"] for gap in success), default=0.0)
    lines += [
        macro("successGapsEstablished", str(len(established))),
        macro("successGapWidest", str(widest_cells)),
        macro("successSeedSpread", f"{seed_spread * 100:.0f}"),
    ]

    review = summary.get("review") or {}
    if review.get("measured"):
        lines += ["", "% --- the review study and the rate sweep ---"]
        rates = review["rates"]
        rate_macro = {"0": "Zero", "60": "Sixty", "120": "OneTwenty", "180": "OneEighty"}
        for arm, entry in review["arms"].items():
            name = ARM_MACRO.get(arm)
            if not name or entry["median_minutes"] is None:
                continue
            lines.append(macro(f"reviewMinutes{name}", f"{entry['median_minutes']:.2f}"))
        for rate in rates:
            suffix = rate_macro.get(rate, rate)
            for arm, value in review["salc_by_rate"][rate].items():
                name = ARM_MACRO.get(arm)
                if name and value is not None:
                    lines.append(macro(f"salc{name}At{suffix}", money(value)))
            order = review["ordering_by_rate"][rate]
            spelled = " $<$ ".join(arm.replace("_", "\\_") for arm in order)
            lines.append(macro(f"orderingAt{suffix}", spelled))
        changes = review["ordering_changes_at_rate"]
        lines.append(macro("orderingChangesAt", changes if changes else "--"))
        lines.append(macro("reviewRates", ", ".join(f"\\${rate}" for rate in rates if rate != "0")))
        # The rates themselves, so prose never types one either.
        for rate in rates:
            lines.append(macro(f"reviewRate{rate_macro.get(rate, rate)}", rate))
        # How far the review term outweighs model cost once it is priced at all.
        shares = []
        for entry in summary["salc"]:
            minutes = review["arms"].get(entry["arm"], {}).get("median_minutes")
            if minutes and entry["model_cost_usd"]:
                human = 120.0 * (minutes * entry["cells_counted"] / 60.0)
                shares.append(human / entry["model_cost_usd"])
        if shares:
            lines += [
                macro("humanOverModelLow", f"{min(shares):.0f}"),
                macro("humanOverModelHigh", f"{max(shares):.0f}"),
            ]
        study = review.get("study") or {}
        lines += [
            macro("reviewItems", str(study.get("items_sampled", "--"))),
            macro("reviewItemsPerArm", str(study.get("items_per_arm", "--"))),
            macro("reviewReviewers", str(study.get("reviewers", "--"))),
        ]

    lines += ["", "% --- why bundle assembly failed ---"]
    taxonomy = summary.get("bundle_assembly_failures", [])
    failed = sum(entry["bundles_failed"] for entry in taxonomy)
    structural = sum(entry["failed_for_structural_reasons_only"] for entry in taxonomy)
    tier_cells = 0
    for index in summary["governance"]:
        for component in index["components"]:
            if component["component"] == "tier_approval":
                tier_cells = max(tier_cells, component.get("cells_applicable", 0))
    lines += [
        macro("assemblyFailures", str(failed)),
        macro("assemblyStructural", str(structural)),
        macro("assemblyOther", str(failed - structural)),
        macro("tierCells", str(tier_cells)),
    ]

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
