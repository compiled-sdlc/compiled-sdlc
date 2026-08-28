#!/usr/bin/env python3
"""Count the manuscript against its word budget.

The venue counts each figure and each table as a fixed number of words, so a
paper that fits on prose alone can still be over. This counts both, and says how
much room is left.

It is a close estimate, not the venue's own count: it strips LaTeX markup,
skips the preamble, the bibliography and comments, and counts what is left.

    python infra/wordcount.py manuscript/main.tex
"""

import argparse
import re
import sys
from pathlib import Path

WORD_BUDGET = 4200
WORDS_PER_FLOAT = 250
REFERENCE_LIMIT = 15

FLOAT_ENVIRONMENTS = ("figure", "figure*", "table", "table*")

STRIP_ENVIRONMENTS = ("thebibliography", "IEEEkeywords", "abstract")
COMMENT = re.compile(r"(?<!\\)%.*")

# Commands whose argument is machinery rather than text: neither the command
# nor what it wraps appears on the page as prose.
DROPPED = (
    "begin",
    "end",
    "bibliographystyle",
    "bibliography",
    "input",
    "graphicspath",
    "label",
    "ref",
    "eqref",
    "markboth",
    "todo",
    "IEEEauthorblockN",
    "IEEEauthorblockA",
    "newcommand",
    "renewcommand",
    "usepackage",
    "documentclass",
    "cite",
)
DROPPED_WITH_ARGUMENT = re.compile(r"\\(?:" + "|".join(DROPPED) + r")\*?(?:\[[^\]]*\])?\{[^{}]*\}")

# Commands whose argument is text that does appear: a section heading is words
# on the page, so the command goes and the argument stays.
BARE_COMMAND = re.compile(r"\\[a-zA-Z@]+\*?(\[[^\]]*\])?")
MATH = re.compile(r"\$[^$]*\$")
BRACES = re.compile(r"[{}]")


def body(text: str) -> str:
    """Everything between \\begin{document} and \\end{document}."""
    start = text.find(r"\begin{document}")
    end = text.find(r"\end{document}")
    return text[start:end] if start >= 0 and end > start else text


def strip_environment(text: str, name: str) -> str:
    pattern = re.compile(
        rf"\\begin\{{{re.escape(name)}\}}.*?\\end\{{{re.escape(name)}\}}", re.DOTALL
    )
    return pattern.sub(" ", text)


def count_floats(text: str) -> dict[str, int]:
    counts = {}
    for name in FLOAT_ENVIRONMENTS:
        counts[name] = len(re.findall(rf"\\begin\{{{re.escape(name)}\}}", text))
    return counts


def count_references(text: str) -> int:
    """Entries in the bibliography, however it is produced."""
    entries = len(re.findall(r"\\bibitem", text))
    return entries


def prose_words(text: str) -> int:
    text = COMMENT.sub(" ", text)
    for name in FLOAT_ENVIRONMENTS + STRIP_ENVIRONMENTS:
        text = strip_environment(text, name)
    text = MATH.sub(" x ", text)
    for _ in range(3):  # nested cases, e.g. a label inside a dropped command
        text, replaced = DROPPED_WITH_ARGUMENT.subn(" ", text)
        if not replaced:
            break
    text = BARE_COMMAND.sub(" ", text)
    text = BRACES.sub(" ", text)
    return len([word for word in text.split() if any(ch.isalnum() for ch in word)])


def report(path: Path, bibliography: Path | None = None) -> int:
    text = path.read_text()
    inner = body(text)
    floats = count_floats(inner)
    float_total = sum(floats.values())
    prose = prose_words(inner)
    counted = prose + float_total * WORDS_PER_FLOAT

    references = count_references(text)
    if bibliography and bibliography.exists():
        references = max(references, len(re.findall(r"^@\w+\{", bibliography.read_text(), re.M)))

    print(f"words        {prose:,} of prose")
    for name, count in floats.items():
        if count:
            print(
                f"             {count} x {name} at {WORDS_PER_FLOAT} words = "
                f"{count * WORDS_PER_FLOAT:,}"
            )
    print(f"counted      {counted:,} of {WORD_BUDGET:,}", end="")
    if counted <= WORD_BUDGET:
        print(f"  ({WORD_BUDGET - counted:,} to spare)")
    else:
        print(f"  ({counted - WORD_BUDGET:,} OVER)")
    print(f"references   {references} of {REFERENCE_LIMIT}", end="")
    print("  (over)" if references > REFERENCE_LIMIT else "")

    todos = len(re.findall(r"\\todo\{", inner))
    if todos:
        print(f"placeholders {todos} \\todo{{}} still to fill")
    return 0 if counted <= WORD_BUDGET and references <= REFERENCE_LIMIT else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--bibliography", type=Path, default=None)
    arguments = parser.parse_args(argv)
    if not arguments.path.exists():
        print(f"no such file: {arguments.path}", file=sys.stderr)
        return 2
    bibliography = arguments.bibliography or arguments.path.with_name("references.bib")
    return report(arguments.path, bibliography)


if __name__ == "__main__":
    raise SystemExit(main())
