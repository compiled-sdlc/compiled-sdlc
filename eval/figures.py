"""The figures, regenerated from the records every time.

No figure is drawn by hand and none is committed: `make eval` writes them into
an untracked directory from the run records, so a figure can never drift from
the numbers it claims to show.

Every figure carries the label of the run set it came from. A pilot says so on
its face, in the title, so that a screenshot of it cannot be mistaken for a
result later.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  - the backend must be set first

from eval.metrics import ArmSummary, pareto_frontier  # noqa: E402

FIGURES_DIR = Path("figures")

# Muted, distinguishable in grey, and stable per protocol across every figure.
ARM_COLOURS = {
    "baseline": "#4a6fa5",
    "lcir": "#a5584a",
    "lcir_no_ast": "#6a8f5f",
    "compressed": "#8a7aa5",
}
DEFAULT_COLOUR = "#666666"

PANELS = (
    ("cost_usd", "cost per cell (USD)"),
    ("total_tokens", "tokens per cell"),
    ("reasoning_tokens", "reasoning tokens per cell"),
    ("turns", "turns per cell"),
    ("wall_time_seconds", "wall time per cell (s)"),
)


def colour(arm: str) -> str:
    return ARM_COLOURS.get(arm, DEFAULT_COLOUR)


def _annotate(figure, label: str) -> None:
    figure.text(
        0.5,
        0.005,
        label,
        ha="center",
        va="bottom",
        fontsize=8,
        color="#8a4a4a" if label.startswith("PILOT") else "#555555",
    )


def pareto(
    summaries: list[ArmSummary],
    label: str,
    directory: Path = FIGURES_DIR,
    intervals: dict | None = None,
) -> Path:
    """Cost against verified success, one point per protocol, frontier marked.

    Both axes carry bootstrap confidence intervals when they are available, so
    the picture says what the run supports rather than only where the points
    landed. Bars resampled over change requests, not cells.
    """
    directory.mkdir(parents=True, exist_ok=True)
    figure, axes = plt.subplots(figsize=(6.5, 4.5))
    frontier = set(pareto_frontier(summaries))
    intervals = intervals or {}

    # Protocols can land on the same point, so they are named in a legend rather
    # than in labels that would overlap into an unreadable smear.
    for summary in summaries:
        entry = intervals.get(summary.arm) or {}
        cost_ci = entry.get("mean_cost")
        rate_ci = entry.get("success_rate")
        name = entry.get("protocol", summary.arm)
        cost = summary.distributions["cost_usd"]
        centre = cost_ci["point"] if cost_ci else cost.median
        rate = rate_ci["point"] if rate_ci else summary.salc.success_rate
        xerr = (
            [[max(centre - cost_ci["ci_low"], 0)], [max(cost_ci["ci_high"] - centre, 0)]]
            if cost_ci
            else None
        )
        yerr = (
            [[max(rate - rate_ci["ci_low"], 0)], [max(rate_ci["ci_high"] - rate, 0)]]
            if rate_ci
            else None
        )
        on_frontier = summary.arm in frontier
        axes.errorbar(
            centre,
            rate,
            xerr=xerr,
            yerr=yerr,
            fmt="o" if on_frontier else "s",
            markersize=10 if on_frontier else 7,
            color=colour(summary.arm),
            ecolor=colour(summary.arm),
            elinewidth=1,
            capsize=3,
            alpha=0.9,
            label=(
                f"{name} — ${centre:.2f}/cell, {rate:.0%} verified"
                + (" (frontier)" if on_frontier else "")
            ),
        )

    axes.set_xlabel("mean model cost per cell (USD); bars are 95% bootstrap intervals")
    axes.set_ylabel("verified success rate; bars are 95% bootstrap intervals")
    axes.set_ylim(-0.05, 1.08)
    axes.set_xlim(left=0)
    axes.grid(True, alpha=0.25, linewidth=0.6)
    axes.set_axisbelow(True)
    axes.set_title("Cost against verified success, by protocol", fontsize=11)
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.legend(loc="lower right", fontsize=8, frameon=False)
    if len(frontier) == len(summaries):
        axes.text(
            0.02,
            0.04,
            "no arm dominates another",
            transform=axes.transAxes,
            fontsize=8,
            color="#555555",
        )
    _annotate(figure, label)
    figure.tight_layout(rect=(0, 0.04, 1, 1))
    path = directory / "pareto-cost-vs-success.png"
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return path


def distributions(summaries: list[ArmSummary], label: str, directory: Path = FIGURES_DIR) -> Path:
    """Median and interquartile range per arm, for every per-cell measure.

    Medians and spreads rather than means: run-to-run variance on this kind of
    work is large enough that an average of a handful of runs says very little.
    """
    directory.mkdir(parents=True, exist_ok=True)
    figure, axes_grid = plt.subplots(1, len(PANELS), figsize=(3.0 * len(PANELS), 4.0))
    arms = [summary.arm for summary in summaries]
    positions = range(len(arms))

    for axes, (measure, title) in zip(axes_grid, PANELS, strict=True):
        for position, summary in zip(positions, summaries, strict=True):
            spread = summary.distributions[measure]
            lower, upper = spread.quartiles
            axes.errorbar(
                position,
                spread.median,
                yerr=[[max(spread.median - lower, 0)], [max(upper - spread.median, 0)]],
                fmt="o",
                markersize=7,
                color=colour(summary.arm),
                ecolor=colour(summary.arm),
                elinewidth=1.2,
                capsize=4,
            )
        axes.set_xticks(list(positions))
        axes.set_xticklabels(arms, rotation=30, ha="right", fontsize=8)
        axes.set_title(title, fontsize=9)
        axes.grid(True, axis="y", alpha=0.25, linewidth=0.6)
        axes.set_axisbelow(True)
        axes.set_ylim(bottom=0)
        axes.spines["top"].set_visible(False)
        axes.spines["right"].set_visible(False)

    figure.suptitle("Per-cell distributions by arm: median and interquartile range", fontsize=11)
    _annotate(figure, label)
    figure.tight_layout(rect=(0, 0.04, 1, 0.96))
    path = directory / "distributions-by-arm.png"
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return path


def write_all(
    summaries: list[ArmSummary],
    label: str,
    directory: Path = FIGURES_DIR,
    intervals: dict | None = None,
) -> list[Path]:
    """Every figure, in the order they are referred to."""
    return [
        pareto(summaries, label, directory, intervals),
        distributions(summaries, label, directory),
    ]
