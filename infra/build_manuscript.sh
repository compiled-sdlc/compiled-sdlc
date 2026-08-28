#!/usr/bin/env bash
#
# Build the manuscript.
#
# The numbers are regenerated first, from the evaluation's own output, so the
# PDF cannot quote a figure the evaluation did not produce. Then latexmk drives
# the usual passes.
#
# The manuscript sources are not tracked in this repository — the hygiene rules
# keep drafts out of it — so this script builds whatever is in manuscript/ and
# says plainly when there is nothing there.
#
# Usage:
#   infra/build_manuscript.sh            regenerate numbers, build, report the budget
#   infra/build_manuscript.sh --clean    remove the build products
#   infra/build_manuscript.sh --watch    rebuild as the sources change

set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

MANUSCRIPT_DIR="manuscript"
MAIN="main"

# IEEEtran may live in the user's own texmf tree: installing into the system
# tree needs administrative rights this machine does not grant.
if [ -d "${HOME}/Library/texmf" ] && [ -z "${TEXMFHOME:-}" ]; then
    export TEXMFHOME="${HOME}/Library/texmf"
fi

if [ ! -f "${MANUSCRIPT_DIR}/${MAIN}.tex" ]; then
    echo "no ${MANUSCRIPT_DIR}/${MAIN}.tex to build"
    echo "the manuscript sources are untracked; they live only on this machine"
    exit 1
fi

if [ "${1:-}" = "--clean" ]; then
    (cd "${MANUSCRIPT_DIR}" && rm -rf build "${MAIN}".{aux,bbl,blg,log,out,pdf,fdb_latexmk,fls})
    echo "cleaned"
    exit 0
fi

if ! command -v pdflatex > /dev/null 2>&1; then
    echo "no pdflatex on PATH; install a TeX distribution to build the manuscript"
    exit 1
fi

if ! kpsewhich IEEEtran.cls > /dev/null 2>&1; then
    echo "IEEEtran.cls is not installed. Without administrative rights:"
    echo "  tlmgr --usermode init-usertree"
    echo "  tlmgr --usermode --repository <a repository for your TeX Live release> install ieeetran"
    exit 1
fi

echo "regenerating the numbers"
if ! uv run python -m eval.manuscript_numbers; then
    echo "could not regenerate the numbers; run make eval first"
    exit 1
fi

cd "${MANUSCRIPT_DIR}" || exit 2

if command -v latexmk > /dev/null 2>&1; then
    if [ "${1:-}" = "--watch" ]; then
        exec latexmk -pdf -pvc "${MAIN}"
    fi
    latexmk -pdf -interaction=nonstopmode -halt-on-error "${MAIN}"
    status=$?
else
    # latexmk is not relocatable into a user texmf tree, so a machine without
    # administrative rights may not have it. The passes it would have run:
    echo "latexmk not found; running the passes directly"
    pdflatex -interaction=nonstopmode -halt-on-error "${MAIN}" > /dev/null &&
        (bibtex "${MAIN}" > /dev/null || true) &&
        pdflatex -interaction=nonstopmode -halt-on-error "${MAIN}" > /dev/null &&
        pdflatex -interaction=nonstopmode -halt-on-error "${MAIN}" > /dev/null
    status=$?
fi

if [ "${status}" -ne 0 ]; then
    echo
    echo "the build failed; the last errors were:"
    grep -E "^(!|l\.[0-9]+)" "${MAIN}.log" | head -20
    exit 1
fi

cd .. || exit 2
echo
echo "built ${MANUSCRIPT_DIR}/${MAIN}.pdf"
uv run python infra/wordcount.py "${MANUSCRIPT_DIR}/${MAIN}.tex"
