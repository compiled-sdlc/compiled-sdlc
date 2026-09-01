#!/usr/bin/env bash
# Assemble the data deposit that the paper's availability statement promises.
#
# The repository carries the recipe; this carries the product. Everything here
# is derived from the recorded runs, and the sanitizer runs first because the
# records were written by a shell on a particular machine and carry its paths.
#
#   bash infra/build_deposit.sh
#
# Writes data/deposit/, which is untracked. The archive is what gets uploaded;
# the repository snapshot is attached to it separately by the release.
set -euo pipefail

cd "$(dirname "$0")/.."
DEPOSIT="data/deposit"

echo "== sanitizing the run records =="
uv run python infra/sanitize_runs.py --out "$DEPOSIT/runs"

echo
echo "== copying the derived results =="
mkdir -p "$DEPOSIT/evaluation" "$DEPOSIT/review" "$DEPOSIT/figures" "$DEPOSIT/bench"
cp data/eval-summary.json "$DEPOSIT/evaluation/"
cp data/review-times.json "$DEPOSIT/review/"
cp figures/*.png "$DEPOSIT/figures/"
cp bench/calibration.json "$DEPOSIT/bench/"
cp bench/prompt-allowance.json "$DEPOSIT/bench/"
cp eval/REVIEW_PROTOCOL.md "$DEPOSIT/review/"

# The review instrument and its key. The study is finished, so the key is
# published: without it nobody can check that the concealment held.
if [ -d data/review ]; then
    cp -R data/review/packet "$DEPOSIT/review/packet"
    cp data/review/key.json "$DEPOSIT/review/"
    cp data/review/HOW-TO-REVIEW.md "$DEPOSIT/review/" 2>/dev/null || true
    [ -f data/review/timings.jsonl ] && cp data/review/timings.jsonl "$DEPOSIT/review/"
fi

echo
echo "== writing the ledger =="
uv run python - <<'PY'
import json, pathlib

deposit = pathlib.Path("data/deposit")
runs = pathlib.Path("runs")

def cells(directory: pathlib.Path) -> int:
    return len(list(directory.glob("*/record.json")))

analysed = cells(runs)
void = cells(runs / "void-cross-service-prompt")
discarded = cells(runs / "defective-cr109-check")
pilot = cells(runs / "pilot-revision-1")

lines = [
    "# Run ledger",
    "",
    "Every cell ever executed, and what became of it. Nothing is deleted; a cell",
    "that does not count is moved out of the matrix and told why here.",
    "",
    f"- **{analysed} analysed** — 20 change requests x 4 protocols x 3 repeated runs.",
    f"- **{void} voided and re-run** — the task framing named only the first of the",
    "  two modules a cross-service change request declares, so every agent was",
    "  instructed away from a module its hidden checks ran in. An apparatus defect,",
    "  not a protocol failure. Kept under `runs/void-cross-service-prompt/`.",
    f"- **{discarded} discarded** — one per protocol, for a change request whose hidden",
    "  check no correct implementation could satisfy: it required a log line to",
    "  carry an identifier the entity offered no way to set. Kept under",
    "  `runs/defective-cr109-check/`.",
    f"- **{pilot} archived pilot cells** — taken under prompt-template revision 1 and",
    "  not comparable with what followed. Kept under `runs/pilot-revision-1/`.",
    "",
    f"Executed for the analysed matrix: {analysed + void}. Executed in total,",
    f"including the pilot and the discarded change request: {analysed + void + discarded + pilot}.",
    "",
    "## What is in this deposit",
    "",
    "| Path | What it is |",
    "|---|---|",
    "| `runs/` | every run record, transcript, patch and IR bundle, sanitized |",
    "| `evaluation/eval-summary.json` | every number in the paper, computed from `runs/` |",
    "| `figures/` | the figures the paper prints |",
    "| `review/` | the review protocol, the concealed packet, its key, the timings |",
    "| `bench/calibration.json` | every hidden check proved red before the change |",
    "| `bench/prompt-allowance.json` | the frozen prompt templates and their digests |",
    "| `SANITIZATION.json` | what was replaced in the records, and with what |",
    "",
    "The harness that produced all of it, and the schemas, change requests and",
    "hidden checks, are in the repository snapshot attached to the same release.",
]
(deposit / "LEDGER.md").write_text("\n".join(lines) + "\n")
print(f"analysed {analysed}, voided {void}, discarded {discarded}, pilot {pilot}")
PY

echo
echo "== leak scan over the assembled archive =="
# The sanitizer guarantees the run records. This gates the whole deposit: the
# derived results, the review packet and its key, the ledger and the figures all
# came from somewhere, and any of them could carry a path the sanitizer never
# saw. Nothing is emitted while a single match stands.
uv run python infra/scan_deposit.py "$DEPOSIT"

echo
echo "== packaging =="
VERSION="$(git describe --tags --abbrev=0 2>/dev/null || echo untagged)"
ZIP="data/compiled-sdlc-data-${VERSION}.zip"
rm -f "$ZIP"
(cd data && zip -qr "$(basename "$ZIP")" deposit)
echo "wrote $ZIP ($(du -h "$ZIP" | cut -f1)), named for tag $VERSION"

echo
echo "== deposit =="
du -sh "$DEPOSIT" | cut -f1
find "$DEPOSIT" -maxdepth 1 -mindepth 1 | sort
