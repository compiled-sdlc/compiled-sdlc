"""`make eval`: every number and every figure, from the run records alone.

Nothing here is carried over from a run, read from a bundle, or remembered
between invocations. Delete the figures and the summary, run it again, and the
same numbers come back — which is the property that lets a result be checked.

The report says at the top what kind of run set it read. A set that has not met
the experiment's own discipline is labelled a pilot, and the label is decided by
the data rather than by a flag, so nothing becomes a result by someone
forgetting to say it is not one.
"""

import argparse
from pathlib import Path

from eval import figures as figures_module
from eval import governance, metrics, review, stats
from eval import records as records_module
from pipelines.common import locks, telemetry

SUMMARY_PATH = Path("data") / "eval-summary.json"

SALC_HEADER = (
    f"{'arm':13s} {'cells':>5s} {'excl':>4s} {'verified':>8s} {'rate':>6s} "
    f"{'model $':>9s} {'tools $':>8s} {'human $':>8s} {'SALC $/ok':>10s}"
)
DISTRIBUTION_HEADER = (
    f"{'arm':13s} {'measure':<20s} {'n':>3s} {'median':>12s} {'q1':>12s} {'q3':>12s} "
    f"{'IQR':>12s} {'max/min':>8s}"
)


def banner(run_set: records_module.RunSet) -> str:
    lines = [
        "=" * 78,
        run_set.label.upper() if run_set.is_pilot else run_set.label,
        "=" * 78,
    ]
    if run_set.is_pilot:
        lines.append("These numbers validate the harness. They are not results and are")
        lines.append("reported in no manuscript, README or figure caption as though they were.")
        for reason in run_set.why_pilot():
            lines.append(f"  - {reason}")
    return "\n".join(lines)


def salc_table(summaries: list[metrics.ArmSummary]) -> str:
    lines = [SALC_HEADER, "-" * len(SALC_HEADER)]
    for summary in summaries:
        value = summary.salc.value
        rendered = f"{value:10.4f}" if value is not None else f"{'undefined':>10s}"
        lines.append(
            f"{summary.arm:13s} {summary.salc.cells:5d} {summary.salc.excluded:4d} "
            f"{summary.salc.verified_count:8d} {summary.salc.success_rate:6.2f} "
            f"{summary.salc.model_cost:9.4f} {summary.salc.tools_cost:8.4f} "
            f"{summary.salc.human_cost:8.4f} {rendered}"
        )
    return "\n".join(lines)


def distribution_table(summaries: list[metrics.ArmSummary]) -> str:
    lines = [DISTRIBUTION_HEADER, "-" * len(DISTRIBUTION_HEADER)]
    for summary in summaries:
        for measure, _ in figures_module.PANELS:
            spread = summary.distributions[measure]
            lower, upper = spread.quartiles
            lines.append(
                f"{summary.arm:13s} {measure:<20s} {spread.n:3d} {spread.median:12.4f} "
                f"{lower:12.4f} {upper:12.4f} {spread.iqr:12.4f} {spread.spread:8.1f}"
            )
    return "\n".join(lines)


def governance_table(indices: list[governance.Index]) -> str:
    header = f"{'arm':13s} {'index':>7s}  " + "  ".join(
        f"{name:>16s}" for name in governance.COMPONENTS
    )
    lines = [header, "-" * len(header)]
    for index in indices:
        value = index.value
        rendered = f"{value:7.2f}" if value is not None else f"{'—':>7s}"
        cells = []
        for name in governance.COMPONENTS:
            component = index.components[name]
            if component.observable:
                # The figure alone hides how much of the arm it rests on: a
                # component scored on two cells of twelve is not the same claim
                # as one scored on all twelve.
                shown = f"{component.value:.2f} ({component.scored}/{component.applicable_cells})"
                if component.set_aside:
                    shown += f" -{component.set_aside}"
            else:
                shown = component.state
            cells.append(f"{shown:>16s}")
        lines.append(f"{index.arm:13s} {rendered}  " + "  ".join(cells))
    lines.append("")
    lines.append("Each figure is followed by the cells it was scored on, out of the cells the")
    lines.append("component applies to.")
    lines.append("`not observable`:  the arm cannot take the check at all — not a zero.")
    lines.append("`not comparable`:  scored under a superseded definition; set aside, never mixed.")
    lines.append("A trailing -n counts cells set aside for that reason.")
    lines.append("`not recorded`:   the arm can, but these runs carry no figure for it.")
    lines.append("Nothing here enters the success denominator — a governance gap is not a")
    lines.append("failed change request, and only the arms that produce IR can even see one.")
    lines.append("")
    lines.append("`tier_approval` is 0.00 for every arm that can take it, and structurally so:")
    lines.append("the provenance ledger is written by the harness, the run is unattended, and")
    lines.append("no path in it records a human approval. It reports a property of running")
    lines.append("without a human in the loop, identical across arms, and separates none.")
    return "\n".join(lines)


def assembly_table(taxonomy: list[dict]) -> str:
    """Why bundle assembly failed, which a single pass-or-fail figure cannot say."""
    lines = ["BUNDLE ASSEMBLY: WHY IT FAILED", ""]
    header = f"{'arm':13s} {'scored':>7s} {'failed':>7s} {'structural only':>16s}  reasons"
    lines += [header, "-" * len(header)]
    for entry in taxonomy:
        reasons = ", ".join(f"{code} x{count}" for code, count in entry["reasons"].items())
        lines.append(
            f"{entry['arm']:13s} {entry['bundles_scored']:7d} {entry['bundles_failed']:7d} "
            f"{entry['failed_for_structural_reasons_only']:16d}  {reasons or '—'}"
        )
    total_failed = sum(entry["bundles_failed"] for entry in taxonomy)
    structural = sum(entry["failed_for_structural_reasons_only"] for entry in taxonomy)
    lines.append("")
    if total_failed:
        lines.append(
            f"{structural} of {total_failed} failures are the missing tier approval and "
            f"nothing else:"
        )
        lines.append("the same unattended-run fact the tier component reports, arriving twice.")
        lines.append("Plans validate at a far higher rate than bundles assemble because the")
        lines.append("difference between the two figures is almost entirely this one cause,")
        lines.append("which has nothing to do with the plan an arm wrote.")
    return "\n".join(lines)


def per_change_request(run_set: records_module.RunSet) -> str:
    arms = run_set.arms
    header = f"{'change request':16s} " + " ".join(f"{arm:>13s}" for arm in arms)
    lines = [header, "-" * len(header)]
    for identifier in run_set.change_requests:
        cells = []
        for arm in arms:
            counted = run_set.for_cell(identifier, arm)
            if not counted:
                cells.append(f"{'-':>13s}")
                continue
            verified = len(metrics.verified(counted))
            cost = metrics.Distribution(
                tuple(record.get("cost_usd", 0.0) for record in counted)
            ).median
            cells.append(f"{verified}/{len(counted)} ${cost:7.4f}")
        lines.append(f"{identifier:16s} " + " ".join(f"{cell:>13s}" for cell in cells))
    lines.append("")
    lines.append("verified/counted and the median cost per cell")
    return "\n".join(lines)


def outcomes(run_set: records_module.RunSet) -> str:
    reasons: dict[str, int] = {}
    for record in run_set.records:
        status = record.get("status", "unknown")
        if status == "completed" and record.get("verified_success"):
            continue
        key = f"{status}/{record.get('error_class') or 'none'}"
        reasons[key] = reasons.get(key, 0) + 1
    if not reasons:
        return "  every recorded cell was a verified success"
    lines = []
    for reason, count in sorted(reasons.items()):
        status = reason.split("/")[0]
        charged = "charged to the arm" if telemetry.counts_towards_the_arm(status) else "excluded"
        lines.append(f"  {count:3d}  {reason:32s} {charged}")
    return "\n".join(lines)


def sensitivity_table(run_set: records_module.RunSet, **options) -> str:
    """SALC as the review rate rises, each arm weighted by its own measured time."""
    rates = metrics.DEFAULT_RATES
    measured = options.pop("per_arm_human_minutes", None) or {}
    header = f"{'arm':13s} {'min/review':>11s} " + " ".join(
        f"{f'@{rate:g}/h':>12s}" for rate in rates
    )
    lines = [header, "-" * len(header)]
    orderings = {rate: [] for rate in rates}
    for arm in run_set.arms:
        per_arm = {**options}
        if arm in measured:
            per_arm["human_minutes"] = measured[arm]
        swept = metrics.sensitivity(run_set, arm, rates, **per_arm)
        for rate, value in swept.items():
            if value is not None:
                orderings[rate].append((value, arm))
        shown = f"{measured[arm]:11.2f}" if arm in measured else f"{'--':>11s}"
        cells = [
            f"{value:12.4f}" if value is not None else f"{'undefined':>12s}"
            for value in swept.values()
        ]
        lines.append(f"{arm:13s} {shown} " + " ".join(cells))
    lines.append("")
    if not measured:
        lines.append("Review time is not measured, so the weighted term contributes nothing and")
        lines.append("every rate gives the same answer. The metric currently rests on model")
        lines.append("cost alone; measuring review time on a sample is what would change that.")
        return "\n".join(lines)

    lines.append("Review time is the per-cell median, counted once per cell, because the")
    lines.append("numerator sums what every attempt consumed. Cheapest arm first:")
    for rate in rates:
        order = " < ".join(arm for _, arm in sorted(orderings[rate]))
        lines.append(f"  @{rate:g}/h  {order}")
    baseline_rate = rates[0]
    for rate in rates[1:]:
        if [a for _, a in sorted(orderings[rate])] != [
            a for _, a in sorted(orderings[baseline_rate])
        ]:
            lines.append("")
            lines.append(f"The ordering is not stable in the rate: it changes by @{rate:g}/h.")
            break
    return "\n".join(lines)


def review_block(run_set: records_module.RunSet, options: dict) -> dict:
    """The review study as the manuscript needs it: times, the sweep, the ordering."""
    measured = options.get("per_arm_human_minutes") or {}
    rates = metrics.DEFAULT_RATES
    arms = {}
    sweep: dict[str, dict[str, float | None]] = {f"{rate:g}": {} for rate in rates}
    for arm in run_set.arms:
        per_arm = {k: v for k, v in options.items() if k != "per_arm_human_minutes"}
        if arm in measured:
            per_arm["human_minutes"] = measured[arm]
        swept = metrics.sensitivity(run_set, arm, rates, **per_arm)
        arms[arm] = {"median_minutes": measured.get(arm)}
        for rate, value in swept.items():
            sweep[f"{rate:g}"][arm] = None if value is None else round(value, 4)
    ordering = {
        rate: [arm for _, arm in sorted((v, a) for a, v in values.items() if v is not None)]
        for rate, values in sweep.items()
    }
    first = ordering[f"{rates[0]:g}"]
    changes_at = next(
        (rate for rate in list(ordering)[1:] if ordering[rate] != first),
        None,
    )
    study = {}
    times = Path("data") / "review-times.json"
    if times.exists():
        import json as _json

        raw = _json.loads(times.read_text())
        per_arm = {entry["items_reviewed"] for entry in raw.get("arms", {}).values()}
        study = {
            "items_sampled": raw.get("items_sampled"),
            "reviewers": raw.get("reviewers"),
            "items_per_arm": per_arm.pop() if len(per_arm) == 1 else None,
            "abandoned": len(raw.get("abandoned") or []),
        }
    return {
        "measured": bool(measured),
        "study": study,
        "arms": arms,
        "rates": [f"{rate:g}" for rate in rates],
        "salc_by_rate": sweep,
        "ordering_by_rate": ordering,
        "ordering_changes_at_rate": changes_at,
    }


#: The four contrasts the design was built to answer, fixed before the run.
#: typed-plan against typed-free isolates the plan obligation; typed-free
#: against prose-free isolates the typing; typed-plan against prose-free is the
#: whole protocol against the ordinary way of working; prose-min against
#: prose-free is the minification control. The two remaining combinations pit a
#: typed protocol against the minification control, which changes two things at
#: once and answers no question the design poses.
PAIRS = (
    ("lcir", "lcir_no_ast"),
    ("lcir_no_ast", "baseline"),
    ("lcir", "baseline"),
    ("compressed", "baseline"),
)


def cache_neutral_block(run_set: records_module.RunSet) -> dict:
    """The same comparison with the caching discount removed."""
    rates = locks.pricing()["models"]
    main = max(rates, key=lambda model: rates[model]["output"])
    input_rate, output_rate = rates[main]["input"], rates[main]["output"]
    arms = {}
    for arm in run_set.arms:
        interval = stats.clustered_bootstrap(
            run_set, stats.neutral_adjusted_cost(arm, input_rate, output_rate)
        )
        arms[arm] = {
            "protocol": records_module.PROTOCOL.get(arm, arm),
            "adjusted_cost": interval.to_dict() if interval else None,
        }
    pairs = []
    for dearer, cheaper in PAIRS:
        if dearer not in run_set.arms or cheaper not in run_set.arms:
            continue
        interval = stats.clustered_bootstrap(
            run_set, stats.neutral_ratio(dearer, cheaper, input_rate, output_rate)
        )
        pairs.append(
            {
                "dearer": dearer,
                "cheaper": cheaper,
                "ratio": interval.to_dict() if interval else None,
                "separated": bool(interval and interval.excludes_one),
            }
        )
    return {
        "note": "every input class repriced at the uncached input rate",
        "priced_at": main,
        "arms": arms,
        "pairs": pairs,
    }


def models_billed(run_set: records_module.RunSet) -> list[dict]:
    """Every model the run actually paid for, largest share first.

    Read off the records rather than the lock: what a cell was billed for is a
    measurement, and the executor's own internal calls go to a second, smaller
    model that no lock section is obliged to describe as such.
    """
    spend: dict[str, float] = {}
    for record in run_set.counted:
        for model, amount in (record.get("cost_by_model") or {}).items():
            value = amount if isinstance(amount, int | float) else amount.get("cost_usd", 0.0)
            spend[model] = spend.get(model, 0.0) + float(value)
    total = sum(spend.values())
    return [
        {
            "model": model,
            "cost_usd": round(cost, 4),
            "share": round(cost / total, 5) if total else 0,
        }
        for model, cost in sorted(spend.items(), key=lambda item: -item[1])
    ]


def bootstrap_block(run_set: records_module.RunSet) -> dict:
    """Effect sizes with intervals, resampled over change requests."""
    per_arm = {}
    for arm in run_set.arms:
        cost = stats.clustered_bootstrap(run_set, stats.mean_cost(arm))
        adjusted = stats.clustered_bootstrap(run_set, stats.adjusted_cost(arm))
        rate = stats.success_rate_interval(run_set, arm)
        per_arm[arm] = {
            "protocol": records_module.PROTOCOL.get(arm, arm),
            "mean_cost": cost.to_dict() if cost else None,
            "adjusted_cost": adjusted.to_dict() if adjusted else None,
            "success_rate": rate.to_dict() if rate else None,
            "within_task_spread": stats.within_task_spread(run_set, arm),
        }
    pairs = []
    for dearer, cheaper in PAIRS:
        if dearer not in run_set.arms or cheaper not in run_set.arms:
            continue
        cost = stats.clustered_bootstrap(run_set, stats.cost_ratio(dearer, cheaper))
        adjusted = stats.clustered_bootstrap(run_set, stats.adjusted_cost_ratio(dearer, cheaper))
        success = stats.clustered_bootstrap(
            run_set, stats.paired_success_difference(cheaper, dearer)
        )
        pairs.append(
            {
                "dearer": dearer,
                "cheaper": cheaper,
                "cost_ratio": cost.to_dict() if cost else None,
                "cost_ratio_separated": bool(cost and cost.excludes_one),
                "adjusted_ratio": adjusted.to_dict() if adjusted else None,
                "adjusted_ratio_separated": bool(adjusted and adjusted.excludes_one),
                "paired_success_difference": success.to_dict() if success else None,
                "success_separated": bool(success and success.excludes_zero),
            }
        )
    return {
        "method": "change-request-clustered bootstrap, percentile interval",
        "resamples": stats.RESAMPLES,
        "seed": stats.BOOTSTRAP_SEED,
        "arms": per_arm,
        "pairs": pairs,
    }


def build(run_set: records_module.RunSet, **options) -> dict:
    """Everything the report says, as data."""
    summaries = metrics.summarise(run_set, **options)
    indices = governance.indices(run_set)
    return {
        "label": run_set.label,
        "is_pilot": run_set.is_pilot,
        "why_pilot": run_set.why_pilot(),
        "cells": len(run_set.records),
        "counted": len(run_set.counted),
        "excluded": len(run_set.excluded),
        "arms": list(run_set.arms),
        "change_requests": list(run_set.change_requests),
        "seeds": run_set.seeds,
        "pricing_captured_on": locks.pricing()["captured_on"],
        "pareto_frontier": metrics.pareto_frontier(summaries),
        "bundle_assembly_failures": governance.assembly_taxonomy(run_set),
        "review": review_block(run_set, options),
        "bootstrap": bootstrap_block(run_set),
        "models_billed": models_billed(run_set),
        "cache_neutral": cache_neutral_block(run_set),
        "salc": [summary.to_dict() for summary in summaries],
        "governance": [index.to_dict() for index in indices],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=records_module.RUNS_DIR)
    parser.add_argument("--figures", type=Path, default=figures_module.FIGURES_DIR)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument(
        "--tools-cost", type=float, default=0.0, help="metered execution cost of the runs"
    )
    parser.add_argument(
        "--human-minutes",
        type=float,
        default=None,
        help="one review time for every arm; overrides the measured study",
    )
    parser.add_argument(
        "--review-times",
        type=Path,
        default=Path("data") / "review-times.json",
        help="per-arm review medians from the study, when it has been run",
    )
    parser.add_argument("--no-figures", action="store_true")
    arguments = parser.parse_args(argv)

    run_set = records_module.load(arguments.runs)
    if not run_set.records:
        print(f"no runs recorded under {arguments.runs}")
        return 1

    # A measured study gives each arm its own review time; the flag, when given,
    # applies one figure to every arm and says so. Neither invents a zero.
    measured = review.human_minutes_by_arm(arguments.review_times)
    if arguments.human_minutes is not None:
        measured = {}
    options = {
        "tools_cost": arguments.tools_cost,
        "human_minutes": arguments.human_minutes,
        "per_arm_human_minutes": measured,
    }
    summaries = metrics.summarise(run_set, **options)
    indices = governance.indices(run_set)

    print(banner(run_set))
    print(
        f"\n{len(run_set.records)} cell(s) under {arguments.runs}: "
        f"{len(run_set.counted)} counted, {len(run_set.excluded)} excluded"
    )
    print(
        f"{len(run_set.change_requests)} change request(s), {len(run_set.arms)} protocol(s), "
        f"{run_set.seeds} independent repetition(s) per cell"
    )
    print(f"prices captured {locks.pricing()['captured_on']}; cost recomputed from tokens")

    print("\n\nSUCCESS-ADJUSTED LIFECYCLE COST\n")
    print(salc_table(summaries))
    print("\n  SALC = (model + tools + rate x review time) / verified successes.")
    print("  A verified success passed the hidden checks and violated no must-invariant.")
    print("  Tools cost is zero: the application runs as local processes, nothing metered.")

    print("\n\nSENSITIVITY TO THE REVIEW RATE\n")
    print(sensitivity_table(run_set, **options))

    print("\n\nGOVERNANCE COMPLETENESS\n")
    print(governance_table(indices))

    print("\n\nPER-CELL DISTRIBUTIONS\n")
    print(distribution_table(summaries))

    print("\n\nPER CHANGE REQUEST\n")
    print(per_change_request(run_set))

    print("\n\nOUTCOMES\n")
    print(outcomes(run_set))

    print("\n\n" + assembly_table(governance.assembly_taxonomy(run_set)))
    frontier = metrics.pareto_frontier(summaries)
    print(f"\n\nPARETO FRONTIER\n\n  {', '.join(frontier)}")
    if len(frontier) == len(summaries):
        print("  No arm dominates another on cost and verified success together.")
    print("  Separation is decided by the bootstrap intervals above, not by the")
    print("  frontier: a protocol on it may still be inseparable from one that is not.")

    summary = build(run_set, **options)
    written = records_module.write_json(arguments.summary, summary)
    print(f"\n\nwrote {written}")
    if not arguments.no_figures:
        intervals = summary.get("bootstrap", {}).get("arms", {})
        for path in figures_module.write_all(
            summaries, run_set.label, arguments.figures, intervals
        ):
            print(f"wrote {path}")

    print(f"\n{run_set.label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
