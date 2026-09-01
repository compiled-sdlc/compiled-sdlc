#!/usr/bin/env python3
"""Make a copy of the run records fit to publish.

The hygiene audit scans *tracked* content. The run records are untracked, so
nothing has ever scanned them, and they carry what a shell on a particular
machine happens to print: home directories, the operator's username, a LAN
address, a local hostname, e-mail addresses quoted out of the target
application's own source. None of that is a measurement and none of it belongs
in a public deposit.

This writes a sanitized copy rather than editing in place. The originals stay as
they were recorded, because a record that has been rewritten is no longer the
record; the deposit is a derived artifact and says so.

What is *not* removed: the pinned model and executor identifiers. They are the
apparatus, the paper names them, and an archive that hid them could not be used
to reproduce anything.

    python infra/sanitize_runs.py [--runs runs/] [--out data/deposit/runs] [--check]
"""

import argparse
import getpass
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.common import locks  # noqa: E402

#: Text files worth rewriting. Everything else is copied byte for byte.
TEXT_SUFFIXES = {".json", ".jsonl", ".log", ".txt", ".patch", ".md"}

PLACEHOLDERS = {
    "home": "/HOME",
    "repo": "/REPO",
    "tmp": "/TMP",
    "user": "OPERATOR",
    "host": "HOST",
    "address": "LAN-ADDRESS",
    "email": "someone@example.invalid",
}


def substitutions(runs: Path) -> list[tuple[re.Pattern, str]]:
    """Every rewrite, most specific first.

    Order matters: the repository path lives under the home directory, so it has
    to be replaced before the home directory is.
    """
    repo = str(locks.REPO_ROOT)
    user = getpass.getuser()
    rules: list[tuple[str, str]] = [
        (re.escape(repo), PLACEHOLDERS["repo"]),
        (r"/private/tmp/[A-Za-z0-9._/-]*", PLACEHOLDERS["tmp"]),
        (r"/(?:Users|home)/[A-Za-z0-9._-]+", PLACEHOLDERS["home"]),
        # Any remaining mention of the operator, e.g. in a shell prompt.
        (re.escape(user), PLACEHOLDERS["user"]),
        (r"\b(?:\d{1,3}\.){3}\d{1,3}\b(?<!0\.0\.0\.0)(?<!127\.0\.0\.1)", PLACEHOLDERS["address"]),
        (r"\b[A-Za-z0-9-]+\.local\b", PLACEHOLDERS["host"]),
        # E-mail addresses, including ones quoted out of the application source.
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", PLACEHOLDERS["email"]),
    ]
    return [(re.compile(pattern), replacement) for pattern, replacement in rules]


def sanitize(text: str, rules: list[tuple[re.Pattern, str]]) -> tuple[str, int]:
    """Apply every rule, reporting how many replacements were made."""
    replacements = 0
    for pattern, replacement in rules:
        text, count = pattern.subn(replacement, text)
        replacements += count
    return text, replacements


def residue(text: str) -> list[str]:
    """Anything left that should not reach a deposit.

    The placeholders are removed first: the substitute for an e-mail address is
    itself shaped like one, and would otherwise report itself as residue.
    """
    for placeholder in PLACEHOLDERS.values():
        text = text.replace(placeholder, " ")
    user = getpass.getuser()
    checks = {
        "absolute home path": r"/(?:Users|home)/[A-Za-z0-9._-]+",
        "operator username": re.escape(user),
        "repository path": re.escape(str(locks.REPO_ROOT)),
        "local hostname": r"\b[A-Za-z0-9-]+\.local\b",
        "e-mail address": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "private address": r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01]))\.[\d.]+\b",
        "credential": r"sk-[A-Za-z0-9_-]{10,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{15,}",
    }
    found = []
    for name, pattern in checks.items():
        if re.search(pattern, text):
            found.append(name)
    return found


def walk(runs: Path, out: Path, check_only: bool) -> dict:
    rules = substitutions(runs)
    counts = {"files": 0, "rewritten": 0, "replacements": 0, "copied": 0, "dirty": []}
    for source in sorted(runs.rglob("*")):
        if not source.is_file():
            continue
        counts["files"] += 1
        target = out / source.relative_to(runs)
        if source.suffix.lower() in TEXT_SUFFIXES:
            text = source.read_text(errors="replace")
            cleaned, replaced = sanitize(text, rules)
            left = residue(cleaned)
            if left:
                counts["dirty"].append((str(source.relative_to(runs)), left))
            if replaced:
                counts["rewritten"] += 1
                counts["replacements"] += replaced
            if not check_only:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(cleaned)
        else:
            counts["copied"] += 1
            if not check_only:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path, default=locks.REPO_ROOT / "runs")
    parser.add_argument("--out", type=Path, default=locks.REPO_ROOT / "data" / "deposit" / "runs")
    parser.add_argument("--check", action="store_true", help="scan without writing")
    arguments = parser.parse_args(argv)

    if not arguments.runs.exists():
        print(f"no run records at {arguments.runs}", file=sys.stderr)
        return 2
    if not arguments.check and arguments.out.exists():
        shutil.rmtree(arguments.out)

    counts = walk(arguments.runs, arguments.out, arguments.check)
    print(f"files            {counts['files']}")
    print(f"rewritten        {counts['rewritten']}  ({counts['replacements']} replacements)")
    print(f"copied verbatim  {counts['copied']}")
    if counts["dirty"]:
        print(f"\nSTILL DIRTY: {len(counts['dirty'])} file(s)", file=sys.stderr)
        for name, kinds in counts["dirty"][:20]:
            print(f"  {name}: {', '.join(kinds)}", file=sys.stderr)
        return 1
    print("\nno home paths, usernames, hostnames, addresses, e-mails or credentials remain")
    if not arguments.check:
        record = {
            "sanitized_from": "runs/",
            "placeholders": PLACEHOLDERS,
            "note": (
                "Derived from the recorded runs. Absolute paths, the operator's "
                "username, host addresses and e-mail addresses are replaced by the "
                "placeholders above. Model and executor identifiers are left intact: "
                "they are the apparatus, and the paper names them."
            ),
            "files": counts["files"],
            "replacements": counts["replacements"],
        }
        (arguments.out.parent / "SANITIZATION.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n"
        )
        print(f"wrote {arguments.out} and {arguments.out.parent / 'SANITIZATION.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
