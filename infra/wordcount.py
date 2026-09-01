#!/usr/bin/env python3
"""Count the manuscript against the venue's own rule.

The target venue is IEEE Computer. Its author information states that a feature
article must not exceed 6,000 words and should not fall below 4,500, that the
count *includes the bibliography and the author biographies*, that each figure
and each table counts as 300 words, and that no more than 20 references may be
cited. An article over the limit may be rejected without review, so the count
that matters is the strict one.

That rule differs from the IEEE Software rule this project previously assumed
(4,200 words, 250 per float, 15 references, bibliography excluded), and the two
disagree in both directions: Computer allows far more prose but bills the
bibliography and charges more per float. Both are reported, the venue's own rule
first, because the fallback venue still has to be satisfiable.

It remains a close estimate rather than the venue's count: it strips LaTeX
markup, skips the preamble and comments, and counts what is left.

    python infra/wordcount.py manuscript/main.tex
"""

import argparse
import re
import sys
from pathlib import Path

# IEEE Computer, feature article. Checked against the venue's author
# information on 2026-08-31.
WORD_BUDGET = 6000
WORD_MINIMUM = 4500
WORDS_PER_FLOAT = 300
REFERENCE_LIMIT = 20
TITLE_WORD_LIMIT = 9
ABSTRACT_WORD_LIMIT = 150
#: The bibliography and the author biographies count toward Computer's limit.
COUNTS_BIBLIOGRAPHY = True

# IEEE Software, the fallback venue, counts differently. Reported alongside so a
# manuscript that fits one is never assumed to fit the other.
FALLBACK = {
    "name": "IEEE Software",
    "budget": 4200,
    "per_float": 250,
    "references": 15,
    "counts_bibliography": False,
}

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
DROPPED_WITH_ARGUMENT = re.compile(r"\\(?:" + "|".join(DROPPED) + r")\*?(?:\[[^\]]*\])?\{")


def drop_with_argument(text: str) -> str:
    """Remove a dropped command and its whole argument, braces and all.

    Matching the argument with a brace-free pattern silently left the contents
    of any command that contained braces --- a \\todo holding an inline
    equation, say --- in the count, so placeholder text was billed against a
    budget it will never occupy. The argument is scanned for its balancing
    brace instead.
    """
    out = []
    position = 0
    while (match := DROPPED_WITH_ARGUMENT.search(text, position)) is not None:
        out.append(text[position : match.start()])
        depth = 1
        index = match.end()
        while index < len(text) and depth:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        position = index
    out.append(text[position:])
    return " ".join(out)


# Commands whose argument is text that does appear: a section heading is words
# on the page, so the command goes and the argument stays.
BARE_COMMAND = re.compile(r"\\[a-zA-Z@]+\*?(\[[^\]]*\])?")
# An escaped dollar is currency in the prose, not a math delimiter. Treating it
# as one pairs it with a real delimiter far away and silently swallows whole
# sections of the paper, which is how this counter under-reported for a while.
MATH = re.compile(r"(?<!\\)\$[^$]*?(?<!\\)\$")
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
    # Balanced-brace scanning already removes nested cases in one pass.
    text = drop_with_argument(text)
    text = BARE_COMMAND.sub(" ", text)
    text = BRACES.sub(" ", text)
    return len([word for word in text.split() if any(ch.isalnum() for ch in word)])


def title_words(text: str) -> int:
    match = re.search(r"\\title\{(.*?)\}\s*\n", text, re.DOTALL)
    if not match:
        return 0
    cleaned = BARE_COMMAND.sub(" ", match.group(1))
    return len([w for w in BRACES.sub(" ", cleaned).split() if any(c.isalnum() for c in w)])


def abstract_words(text: str) -> int:
    match = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", text, re.DOTALL)
    return prose_words(match.group(1)) if match else 0


def bibliography_words(bibliography: Path | None) -> int:
    """What a rendered reference list costs, when the venue bills it.

    IEEE Computer counts the bibliography against the limit. A .bib file is not
    the rendered list, so this counts the fields that reach the page --- author,
    title, venue, year --- and ignores the keys and the markup that do not.
    """
    if not bibliography or not bibliography.exists():
        return 0
    total = 0
    for field in re.findall(
        r"\b(?:author|title|journal|booktitle|publisher|series|note)\s*=\s*[{\"](.+?)[}\"]\s*,",
        bibliography.read_text(),
        re.DOTALL,
    ):
        total += len([w for w in BRACES.sub(" ", field).split() if any(c.isalnum() for c in w)])
    return total


def report(path: Path, bibliography: Path | None = None) -> int:
    text = path.read_text()
    inner = body(text)
    floats = count_floats(inner)
    float_total = sum(floats.values())
    prose = prose_words(inner)
    abstract = abstract_words(text)
    bib = bibliography_words(bibliography)

    references = count_references(text)
    if bibliography and bibliography.exists():
        references = max(references, len(re.findall(r"^@\w+\{", bibliography.read_text(), re.M)))

    # The venue's own rule, which is the one that decides whether it is read.
    counted = prose + abstract + bib + float_total * WORDS_PER_FLOAT
    print("IEEE Computer (feature article) — the venue's rule")
    print(f"  prose            {prose:,}")
    print(f"  abstract         {abstract:,}")
    print(f"  bibliography     {bib:,}  (Computer counts it)")
    for name, count in floats.items():
        if count:
            print(f"  {count} x {name:<12s} {count * WORDS_PER_FLOAT:,}  (at {WORDS_PER_FLOAT})")
    print(f"  counted          {counted:,} of {WORD_BUDGET:,}", end="")
    if counted > WORD_BUDGET:
        print(f"  ({counted - WORD_BUDGET:,} OVER)")
    elif counted < WORD_MINIMUM:
        print(f"  ({WORD_MINIMUM - counted:,} UNDER the {WORD_MINIMUM:,} minimum)")
    else:
        print(f"  ({WORD_BUDGET - counted:,} to spare)")
    print(f"  references       {references} of {REFERENCE_LIMIT}", end="")
    print("  (OVER)" if references > REFERENCE_LIMIT else "")
    title = title_words(text)
    print(f"  title            {title} of {TITLE_WORD_LIMIT} words", end="")
    print("  (OVER)" if title > TITLE_WORD_LIMIT else "")
    print(f"  abstract         {abstract} of {ABSTRACT_WORD_LIMIT} words", end="")
    print("  (OVER)" if abstract > ABSTRACT_WORD_LIMIT else "")

    # The fallback venue counts differently and has to stay satisfiable too.
    other = prose + float_total * FALLBACK["per_float"]
    print()
    print(
        f"{FALLBACK['name']} (fallback) — bibliography excluded, {FALLBACK['per_float']} per float"
    )
    print(f"  counted          {other:,} of {FALLBACK['budget']:,}", end="")
    print(
        f"  ({other - FALLBACK['budget']:,} OVER)"
        if other > FALLBACK["budget"]
        else f"  ({FALLBACK['budget'] - other:,} to spare)"
    )
    print(f"  references       {references} of {FALLBACK['references']}", end="")
    print("  (OVER)" if references > FALLBACK["references"] else "")

    todos = len(re.findall(r"\\todo\{", inner))
    if todos:
        print(f"\nplaceholders     {todos} \\todo{{}} still to fill")

    within = (
        counted <= WORD_BUDGET
        and references <= REFERENCE_LIMIT
        and title <= TITLE_WORD_LIMIT
        and abstract <= ABSTRACT_WORD_LIMIT
    )
    return 0 if within else 1


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
