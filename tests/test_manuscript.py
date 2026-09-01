"""Tests for the manuscript's build machinery.

The manuscript sources are untracked, so what is tested here is the recipe: the
generator that turns the evaluation's output into the macros the paper quotes,
and the counter that holds it to its word budget. The property that matters is
that a number the evaluation did not produce has no macro, and so cannot be
stated in the paper at all.
"""

import json
import sys
from pathlib import Path

import pytest

from eval import manuscript_numbers
from pipelines.common import locks

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "infra"))

import wordcount  # noqa: E402  - the counter is a script, not a package


def a_summary(**overrides) -> dict:
    summary = {
        "label": "PILOT — harness validation only, not results",
        "is_pilot": True,
        "why_pilot": ["2 seed(s) per cell"],
        "cells": 8,
        "counted": 8,
        "excluded": 0,
        "arms": ["baseline", "lcir"],
        "change_requests": ["CR-101", "CR-102"],
        "seeds": 2,
        "pricing_captured_on": "2026-08-28",
        "pareto_frontier": ["baseline"],
        "salc": [
            {
                "arm": "baseline",
                "cells_counted": 4,
                "verified": 4,
                "success_rate": 1.0,
                "salc_usd_per_verified": 0.1,
                "total_cost_usd": 0.4,
                "distributions": {
                    "cost_usd": {"median": 0.1, "q1": 0.08, "q3": 0.12, "spread": 1.5},
                    "total_tokens": {"median": 1000.0},
                    "reasoning_tokens": {"median": 20.0},
                    "turns": {"median": 5.0},
                    "wall_time_seconds": {"median": 30.0},
                },
            },
            {
                "arm": "lcir",
                "cells_counted": 4,
                "verified": 2,
                "success_rate": 0.5,
                "salc_usd_per_verified": 0.6,
                "total_cost_usd": 1.2,
                "distributions": {
                    "cost_usd": {"median": 0.3, "q1": 0.25, "q3": 0.35, "spread": 1.4},
                    "total_tokens": {"median": 4000.0},
                    "reasoning_tokens": {"median": 900.0},
                    "turns": {"median": 20.0},
                    "wall_time_seconds": {"median": 120.0},
                },
            },
        ],
        "governance": [
            {
                "arm": "baseline",
                "observable": False,
                "index": None,
                "components": [
                    {"component": name, "state": "not observable", "value": None}
                    for name in (
                        "plan_validity",
                        "bundle_assembly",
                        "tier_approval",
                        "evidence_path",
                        "provenance",
                    )
                ],
            },
            {
                "arm": "lcir",
                "observable": True,
                "index": 0.8,
                "components": [
                    {"component": "plan_validity", "state": "scored", "value": 0.9},
                    {"component": "bundle_assembly", "state": "scored", "value": 0.7},
                    {"component": "tier_approval", "state": "scored", "value": 1.0},
                    {"component": "evidence_path", "state": "not recorded", "value": None},
                    {"component": "provenance", "state": "not recorded", "value": None},
                ],
            },
        ],
    }
    summary.update(overrides)
    return summary


def macros(summary: dict) -> dict[str, str]:
    """The generated macros, as a name-to-value mapping."""
    found = {}
    for line in manuscript_numbers.build(summary):
        if line.startswith("\\newcommand"):
            name = line.split("{\\", 1)[1].split("}", 1)[0]
            found[name] = line.split("}{", 1)[1].rsplit("}", 1)[0]
    return found


# --- what the manuscript may quote -----------------------------------------


def test_every_measurement_becomes_a_macro():
    found = macros(a_summary())
    assert found["salcBaseline"] == "0.1000"
    assert found["costLcir"] == "0.3000"
    assert found["verifiedLcir"] == "2"
    assert found["successRateLcir"] == "50"
    assert found["reasoningLcir"] == "900"


def test_the_run_set_label_is_a_macro_so_a_table_carries_it():
    assert macros(a_summary())["runLabel"] == "PILOT"
    assert macros(a_summary(is_pilot=False))["runLabel"] == "full run"


def test_an_arm_that_verified_nothing_has_no_number_to_quote():
    """A ratio that does not exist is a placeholder, never a zero."""
    summary = a_summary()
    summary["salc"][0]["salc_usd_per_verified"] = None
    assert "\\todo" in macros(summary)["salcBaseline"]


def test_an_unmeasured_governance_component_says_which_kind_of_absence():
    found = macros(a_summary())
    assert found["gciLcirEvidencePath"] == "not recorded"
    assert found["gciBaselinePlanValidity"] == "not observable"
    assert found["gciBaseline"] == "not observable"


def test_the_pinned_apparatus_is_read_from_the_lock_files():
    found = macros(a_summary())
    assert found["pinCommit"] == locks.target()["target"]["commit"][:12]
    assert found["pinModel"] == locks.executor()["model"]["id"]
    assert found["pinExecutorVersion"] == locks.executor()["cli"]["version"]
    assert found["budgetCost"] == f"{locks.executor()['budget']['max_cost_usd']:.2f}"


def test_the_cost_ratios_are_derived_not_typed():
    found = macros(a_summary())
    assert found["irPremium"] == "3.0", "0.30 against 0.10"
    assert "\\todo" in macros(a_summary(salc=[]))["irPremium"]


def test_large_numbers_are_grouped_for_typesetting():
    summary = a_summary()
    summary["salc"][0]["distributions"]["total_tokens"]["median"] = 288674.0
    assert macros(summary)["tokensBaseline"] == "288\\,674"


def test_the_generator_refuses_without_an_evaluation(tmp_path, capsys):
    assert manuscript_numbers.main(["--summary", str(tmp_path / "absent.json")]) == 1
    assert "run make eval first" in capsys.readouterr().out


def test_the_generator_writes_a_file_the_manuscript_can_input(tmp_path):
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps(a_summary()))
    output = tmp_path / "generated" / "numbers.tex"
    assert manuscript_numbers.main(["--summary", str(summary), "--output", str(output)]) == 0
    text = output.read_text()
    assert text.startswith("% Written by")
    assert "\\newcommand{\\salcBaseline}" in text


# --- the word budget -------------------------------------------------------

A_PAPER = r"""
\documentclass{IEEEtran}
\begin{document}
\title{A Title}
\begin{abstract}
Words in the abstract are not counted here.
\end{abstract}
\section{One}
One two three four five six seven eight nine ten.
\begin{figure}[t]
\caption{A caption whose words do not count; the figure counts as a block.}
\end{figure}
\begin{table}[t]
\caption{Likewise.}
\end{table}
\todo{something}
\bibliographystyle{IEEEtran}
\end{document}
"""


def test_prose_is_counted_without_its_markup():
    """The title and the heading are words on the page; the machinery is not."""
    counted = wordcount.prose_words(wordcount.body(A_PAPER))
    assert counted == 13, "two in the title, one in the heading, ten in the sentence"


def test_a_placeholder_is_not_counted_as_prose_it_replaces():
    with_todo = wordcount.prose_words(wordcount.body(A_PAPER))
    without = wordcount.prose_words(wordcount.body(A_PAPER.replace("\\todo{something}", "")))
    assert with_todo == without


def test_machinery_is_not_mistaken_for_prose():
    """An environment marker or a bibliography command is not a word on the page."""
    plain = "\\begin{document}\\section{One}Two three four.\\end{document}"
    with_machinery = (
        "\\begin{document}\\section{One}Two three four."
        "\\bibliographystyle{IEEEtran}\\bibliography{references}"
        "\\label{sec:x}\\cite{lenses}\\end{document}"
    )
    assert wordcount.prose_words(wordcount.body(plain)) == 4
    assert wordcount.prose_words(wordcount.body(with_machinery)) == 4


def test_a_figure_and_a_table_each_cost_a_block_of_the_budget(tmp_path):
    counts = wordcount.count_floats(wordcount.body(A_PAPER))
    assert counts["figure"] == 1
    assert counts["table"] == 1
    assert wordcount.WORDS_PER_FLOAT == 300


def test_the_budget_is_reported_against_the_limit(tmp_path, capsys):
    path = tmp_path / "main.tex"
    path.write_text(A_PAPER)
    assert wordcount.report(path) == 0
    out = capsys.readouterr().out
    assert "of 6,000" in out
    assert "to spare" in out
    assert "1 \\todo{} still to fill" in out


def test_going_over_the_budget_is_a_failure(tmp_path, capsys):
    path = tmp_path / "main.tex"
    path.write_text(A_PAPER.replace("\\section{One}", "\\section{One}\n" + "word " * 7000))
    assert wordcount.report(path) == 1
    assert "OVER" in capsys.readouterr().out


def test_too_many_references_is_a_failure(tmp_path, capsys):
    path = tmp_path / "main.tex"
    path.write_text(A_PAPER)
    bibliography = tmp_path / "references.bib"
    bibliography.write_text("\n".join(f"@article{{key{n},\n}}" for n in range(21)))
    assert wordcount.report(path, bibliography) == 1
    assert "OVER" in capsys.readouterr().out


def test_the_counter_reports_a_missing_file(capsys):
    assert wordcount.main(["nowhere/main.tex"]) == 2


# --- the build recipe ------------------------------------------------------


def test_the_build_script_says_so_when_there_is_nothing_to_build(tmp_path):
    """The sources are untracked; a fresh clone has none."""
    script = (REPO / "infra" / "build_manuscript.sh").read_text()
    assert "the manuscript sources are untracked" in script
    assert "eval.manuscript_numbers" in script, "the numbers are regenerated before every build"


@pytest.mark.skipif(
    not (REPO / "manuscript" / "main.tex").exists(),
    reason="the manuscript sources are untracked and are not on this machine",
)
def test_the_manuscript_quotes_no_hand_typed_measurement():
    """Every number in the paper comes through a macro the evaluation generated."""
    import re

    text = (REPO / "manuscript" / "main.tex").read_text()
    body = wordcount.body(text)
    body = re.sub(r"\\begin\{table\}.*?\\end\{table\}", " ", body, flags=re.DOTALL)
    body = re.sub(r"\\(cite|ref|label|input|graphicspath|url)\{[^}]*\}", " ", body)
    body = re.sub(r"\\todo\{.*?\}", " ", body, flags=re.DOTALL)
    # The author block is an address, not a measurement, and its \thanks nests
    # braces, so it is removed by scanning for the balancing brace.
    start = body.find("\\author{")
    if start >= 0:
        depth, index = 0, start + len("\\author")
        while index < len(body):
            if body[index] == "{":
                depth += 1
            elif body[index] == "}":
                depth -= 1
                if depth == 0:
                    index += 1
                    break
            index += 1
        body = body[:start] + " " + body[index:]

    # What is left may carry numbers only where they are part of a cited
    # result, a section number, or an equation.
    def bare(token: str) -> str:
        """The number itself, without the punctuation or markup around it."""
        return token.rstrip(",.").removesuffix("%").removesuffix("\\").rstrip(",.")

    # Section numbers, small counts and the factorial's dimensions are structure,
    # not measurement.
    structural = {"1", "2", "4", "5", "25"}
    suspicious = [
        token
        for token in re.findall(r"(?<![\\{a-zA-Z])\d[\d.,]*\\?%?", body)
        if bare(token) not in structural
    ]
    quoted_from_literature = {
        "1.2",
        "5.0",
        "12",
        "38",
        "27.9",
        "1.8",
        "2025",
        # AgentDiet's reported reductions, the log-format study's cost/token
        # figures, and the retention levels the compression literature studies.
        "39.9",
        "59.7",
        "21.1",
        "35.9",
        "67",
        "17",
        "50",
        "20",
        # Identifiers rather than figures: parity for a ratio, the archived
        # release, and the licence the archive is under.
        "1.0",
        "1.0.0",
        "2.0",
    }
    unexplained = [token for token in suspicious if bare(token) not in quoted_from_literature]
    assert unexplained == [], f"hand-typed numbers in the manuscript: {unexplained}"


def test_no_sentence_appears_twice():
    """A sentence in two places is an editing accident, not emphasis.

    Whole paragraphs were duplicated between the threats section and the
    conclusion at one point, which a word count cannot see and a reader
    certainly can.
    """
    import re

    text = (REPO / "manuscript" / "main.tex").read_text()
    body = wordcount.body(text)
    body = re.sub(r"\\begin\{(table|figure)\}.*?\\end\{\1\}", " ", body, flags=re.DOTALL)
    body = re.sub(r"%.*", " ", body)
    prose = " ".join(body.split())
    # Sentences long enough that a repeat cannot be coincidence.
    sentences = [
        normalised
        for sentence in re.split(r"(?<=[.?!])\s+", prose)
        if len((normalised := " ".join(sentence.split())).split()) >= 8
    ]
    seen: dict[str, int] = {}
    for sentence in sentences:
        seen[sentence] = seen.get(sentence, 0) + 1
    repeated = [sentence for sentence, count in seen.items() if count > 1]
    assert repeated == [], f"sentences appearing more than once: {repeated}"
