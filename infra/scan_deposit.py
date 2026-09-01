#!/usr/bin/env python3
"""Refuse to publish a deposit that leaks anything about the machine it came from.

`infra/sanitize_runs.py` guarantees the run records. This checks the whole
assembled archive, which is a larger claim: the evaluation summary, the review
packet and its key, the ledger and the figures were all produced somewhere, and
any of them could carry a path the sanitizer never looked at. The builder calls
this before it makes the zip, so the sanitizer's guarantee becomes the builder's
precondition rather than a step someone remembered to run.

What it deliberately does not flag: model and executor identifiers. They are the
apparatus, the paper names them, and an archive that hid them could reproduce
nothing.

    python infra/scan_deposit.py data/deposit
"""

import re
import sys
from pathlib import Path

#: Anything a person could read. Binary files are not scanned; a PNG cannot
#: carry a home directory in a form that matters here.
TEXTUAL = {".json", ".jsonl", ".log", ".txt", ".patch", ".md", ".java", ".yaml", ".yml", ".tex"}

#: The sanitizer's substitutes. Removed before scanning, because the stand-in
#: for an e-mail address is itself shaped like one.
PLACEHOLDERS = (
    "/HOME",
    "/REPO",
    "/TMP",
    "OPERATOR",
    "LAN-ADDRESS",
    "HOST",
    "someone@example.invalid",
)

CHECKS = {
    "absolute home path": r"/(?:Users|home)/[A-Za-z0-9._-]+",
    "local hostname": r"\b[A-Za-z0-9-]+\.local\b",
    "private address": r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.[\d.]+\b",
    "e-mail address": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "credential": r"sk-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{15,}",
}


def scan(deposit: Path) -> tuple[int, list[tuple[str, str]]]:
    compiled = {name: re.compile(pattern) for name, pattern in CHECKS.items()}
    leaks: list[tuple[str, str]] = []
    scanned = 0
    for path in sorted(deposit.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXTUAL:
            continue
        scanned += 1
        text = path.read_text(errors="replace")
        for placeholder in PLACEHOLDERS:
            text = text.replace(placeholder, " ")
        for name, pattern in compiled.items():
            if pattern.search(text):
                leaks.append((str(path.relative_to(deposit)), name))
    return scanned, leaks


def main(argv: list[str]) -> int:
    deposit = Path(argv[1]) if len(argv) > 1 else Path("data/deposit")
    if not deposit.exists():
        print(f"no deposit at {deposit}", file=sys.stderr)
        return 2
    scanned, leaks = scan(deposit)
    print(f"scanned {scanned} text files")
    if leaks:
        print(f"\nLEAK: {len(leaks)} match(es); the archive is not fit to publish", file=sys.stderr)
        for name, kind in leaks[:20]:
            print(f"  {name}: {kind}", file=sys.stderr)
        if len(leaks) > 20:
            print(f"  ... and {len(leaks) - 20} more", file=sys.stderr)
        return 1
    print("clean: no paths, hostnames, addresses, e-mails or credentials")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
