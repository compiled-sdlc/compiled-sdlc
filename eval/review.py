#!/usr/bin/env python3
"""The review-time study: sampling, concealment, timing and ingestion.

`T_human` is the one term of SALC nobody can read off a machine, and a review
study that lets the reviewer see which arm produced a change measures their
expectations instead. Everything here exists to make the concealment a property
of the code rather than of the reviewer's good intentions.

eval/REVIEW_PROTOCOL.md is the protocol; this is its implementation.

    python -m eval.review sample [--seed N]
    python -m eval.review verify
    python -m eval.review start <item> | stop <item> | abandon <item> [--why ...]
    python -m eval.review status
    python -m eval.review ingest
"""

import argparse
import hashlib
import json
import random
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from eval import records as records_module
from eval.metrics import Distribution
from pipelines.common import changerequests
from pipelines.common.runner import ARMS
from pipelines.common.workspace import ARTIFACT_DIRECTORY

PACKET_NAME = "packet"
KEY_NAME = "key.json"
TIMINGS_NAME = "timings.jsonl"
OUTPUT_NAME = "review-times.json"

#: An item still open after this long is treated as abandoned. Without a ceiling
#: a single forgotten item dominates every median.
CEILING_MINUTES = 45.0


class ReviewError(RuntimeError):
    """Something that would invalidate the study if it were allowed."""


# --- sampling ---------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """One change put in front of the reviewer, under an opaque name."""

    item: str
    run_id: str
    change_request: str
    arm: str
    seed: int


def digest(run_id: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{run_id}".encode()).hexdigest()[:12]


def choose(run_set: records_module.RunSet) -> list[dict]:
    """One cell per change request and arm: the lowest seed that completed.

    A rule rather than a judgement, and one that does not look at the outcome.
    Cells that completed but failed verification are kept --- the review cost of
    a bad change is the cost the metric exists to capture.
    """
    best: dict[tuple[str, str], dict] = {}
    for record in run_set.counted:
        key = (record["change_request"], record["arm"])
        if key not in best or record["seed"] < best[key]["seed"]:
            best[key] = record
    return [best[key] for key in sorted(best)]


def application_diff(patch: Path) -> str:
    """What the run did to the application, with the arm's own artifacts left out.

    The workspace itself is not kept, but each cell keeps the patch it produced.
    That patch includes whatever the arm placed --- the IR arms write a bundle,
    the compressed arm a minified change request --- and either would name the
    arm in the diff's first line, so the artifact directory is dropped here.
    """
    if not patch.exists():
        raise ReviewError(f"no patch kept at {patch}")
    kept: list[str] = []
    keeping = False
    for line in patch.read_text(errors="replace").splitlines(keepends=True):
        if line.startswith("diff --git "):
            # "diff --git a/<path> b/<path>" — the arm's own artifacts start here.
            target = line.split(" b/", 1)[-1].strip()
            keeping = not target.startswith(f"{ARTIFACT_DIRECTORY}/")
        if keeping:
            kept.append(line)
    return "".join(kept)


def request_sheet(request: changerequests.ChangeRequest) -> str:
    """The work, in one rendering, for every item.

    Built from the change request's own brief, never from an arm's presentation
    of it: the framing is the independent variable and must not reach the
    reviewer.
    """
    brief = request.brief()
    lines = [
        "# Change request",
        "",
        brief["statement"].strip(),
        "",
        "## What the change has to do",
        "",
    ]
    lines += [f"- {item['statement']}" for item in brief["behaviours"]]
    if brief["boundaries"]:
        lines += ["", "## What it must not do", ""]
        lines += [f"- {item['statement']}" for item in brief["boundaries"]]
    if brief["context"]:
        lines += ["", "## Where this lives", "", brief["context"].strip()]
    if brief["evidence"]:
        lines += ["", "## What was observed", "", brief["evidence"]["summary"].strip()]
    return "\n".join(lines) + "\n"


def sample(runs: Path, out: Path, seed: int) -> list[Item]:
    """Build the review packet and the key that undoes it."""
    run_set = records_module.load(runs)
    if not run_set.counted:
        raise ReviewError(f"no completed cells under {runs}")
    requests = {request.id: request for request in changerequests.load_all()}

    salt = secrets.token_hex(8)
    chosen = choose(run_set)
    items = [
        Item(
            item=digest(record["run_id"], salt),
            run_id=record["run_id"],
            change_request=record["change_request"],
            arm=record["arm"],
            seed=record["seed"],
        )
        for record in chosen
    ]
    random.Random(seed).shuffle(items)

    packet = out / PACKET_NAME
    packet.mkdir(parents=True, exist_ok=True)
    for item in items:
        directory = packet / item.item
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "request.md").write_text(request_sheet(requests[item.change_request]))
        (directory / "change.patch").write_text(application_diff(runs / item.run_id / "diff.patch"))

    out.mkdir(parents=True, exist_ok=True)
    (out / KEY_NAME).write_text(
        json.dumps(
            {
                "salt": salt,
                "sampling_seed": seed,
                "ceiling_minutes": CEILING_MINUTES,
                "items": [
                    {
                        "item": item.item,
                        "run_id": item.run_id,
                        "change_request": item.change_request,
                        "arm": item.arm,
                        "seed": item.seed,
                    }
                    for item in items
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    (out / "ORDER.txt").write_text(
        "Review these in order, one at a time.\n\n" + "\n".join(item.item for item in items) + "\n"
    )
    return items


# --- concealment --------------------------------------------------------------


def leak_terms() -> list[str]:
    """Everything a packet must never contain."""
    terms = [*ARMS, ARTIFACT_DIRECTORY, "seed1", "seed2", "seed3", "__"]
    terms += [request.id for request in changerequests.load_all()]
    return terms


def verify(out: Path) -> list[str]:
    """Re-read every packet file and report anything that identifies an arm."""
    packet = out / PACKET_NAME
    if not packet.exists():
        raise ReviewError(f"no packet at {packet}; sample first")
    terms = leak_terms()
    problems: list[str] = []
    for path in sorted(packet.rglob("*")):
        if not path.is_file():
            continue
        content = path.read_text(errors="replace")
        for term in terms:
            if term in content:
                problems.append(f"{path.relative_to(out)}: contains {term!r}")
    return problems


# --- timing -------------------------------------------------------------------


def read_timings(out: Path) -> list[dict]:
    path = out / TIMINGS_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_timing(out: Path, entry: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / TIMINGS_NAME).open("a") as sink:
        sink.write(json.dumps(entry, sort_keys=True) + "\n")


def state(out: Path) -> tuple[dict | None, set[str]]:
    """The item currently open, and every item already finished."""
    open_item: dict | None = None
    finished: set[str] = set()
    for entry in read_timings(out):
        if entry["event"] == "start":
            open_item = entry
        else:
            open_item = None
            finished.add(entry["item"])
    return open_item, finished


def known_items(out: Path) -> set[str]:
    key = out / KEY_NAME
    if not key.exists():
        raise ReviewError(f"no key at {key}; sample first")
    return {entry["item"] for entry in json.loads(key.read_text())["items"]}


def start(out: Path, item: str) -> str:
    if item not in known_items(out):
        raise ReviewError(f"{item} is not in the packet")
    open_item, finished = state(out)
    if open_item is not None:
        raise ReviewError(f"{open_item['item']} is still open; stop or abandon it first")
    if item in finished:
        raise ReviewError(f"{item} has already been reviewed; a second reading is a different task")
    append_timing(out, {"event": "start", "item": item, "at": time.time()})
    return f"started {item}"


def finish(out: Path, item: str, event: str, why: str = "") -> str:
    open_item, _ = state(out)
    if open_item is None or open_item["item"] != item:
        raise ReviewError(f"{item} is not open")
    elapsed = (time.time() - open_item["at"]) / 60.0
    entry = {"event": event, "item": item, "at": time.time(), "minutes": round(elapsed, 3)}
    if why:
        entry["why"] = why
    if event == "stop" and elapsed > CEILING_MINUTES:
        entry = {**entry, "event": "abandon", "why": f"over the {CEILING_MINUTES:g} minute ceiling"}
        append_timing(out, entry)
        return f"{item} ran past the ceiling and is abandoned, not timed"
    append_timing(out, entry)
    return f"{event} {item} at {elapsed:.1f} minutes"


# --- ingestion ----------------------------------------------------------------


def ingest(out: Path) -> dict:
    """Join timings to the key and reduce them to a per-arm figure."""
    key_path = out / KEY_NAME
    if not key_path.exists():
        raise ReviewError(f"no key at {key_path}; sample first")
    key = json.loads(key_path.read_text())
    arm_of = {entry["item"]: entry["arm"] for entry in key["items"]}

    timed: dict[str, list[float]] = {arm: [] for arm in ARMS}
    abandoned: list[dict] = []
    for entry in read_timings(out):
        if entry["event"] == "stop":
            timed.setdefault(arm_of[entry["item"]], []).append(entry["minutes"])
        elif entry["event"] == "abandon":
            abandoned.append(
                {"arm": arm_of[entry["item"]], "why": entry.get("why", ""), "item": entry["item"]}
            )

    arms = {}
    for arm, minutes in timed.items():
        distribution = Distribution(tuple(minutes))
        arms[arm] = {
            "items_reviewed": distribution.n,
            "median_minutes": round(distribution.median, 3) if distribution.n else None,
            "iqr_minutes": (
                [round(value, 3) for value in distribution.quartiles] if distribution.n else None
            ),
        }
    return {
        "schema_version": 1,
        "protocol": "eval/REVIEW_PROTOCOL.md",
        "sampling_seed": key["sampling_seed"],
        "ceiling_minutes": key["ceiling_minutes"],
        "items_sampled": len(key["items"]),
        "reviewers": 1,
        "arms": arms,
        "abandoned": abandoned,
    }


def human_minutes_by_arm(path: Path) -> dict[str, float]:
    """What `make eval` reads: each arm's measured median, where there is one."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text())
    return {
        arm: entry["median_minutes"]
        for arm, entry in payload.get("arms", {}).items()
        if entry.get("median_minutes") is not None
    }


# --- command line -------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("data") / "review")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sampler = subparsers.add_parser("sample", help="build the packet and its key")
    sampler.add_argument("--runs", type=Path, default=records_module.RUNS_DIR)
    sampler.add_argument("--seed", type=int, default=1, help="shuffles the review order")
    subparsers.add_parser("verify", help="check the packet gives no arm away")
    for name, help_text in (
        ("start", "open an item"),
        ("stop", "close an item and time it"),
        ("abandon", "drop an item from the sample"),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("item")
        if name == "abandon":
            command.add_argument("--why", default="interrupted")
    subparsers.add_parser("status", help="what is open and what is left")
    ingester = subparsers.add_parser("ingest", help="reduce the timings to a per-arm figure")
    ingester.add_argument(
        "--output", type=Path, default=Path("data") / OUTPUT_NAME, help="where eval reads it"
    )

    arguments = parser.parse_args(argv)
    out = arguments.out

    try:
        if arguments.command == "sample":
            items = sample(arguments.runs, out, arguments.seed)
            problems = verify(out)
            print(f"sampled {len(items)} items into {out / PACKET_NAME}")
            print(f"key written to {out / KEY_NAME} — do not open it before reviewing")
            if problems:
                print("\nCONCEALMENT FAILED:", file=sys.stderr)
                for problem in problems:
                    print(f"  {problem}", file=sys.stderr)
                return 1
            print("concealment checked: nothing in the packet names an arm")
            return 0

        if arguments.command == "verify":
            problems = verify(out)
            for problem in problems:
                print(problem, file=sys.stderr)
            print("no leaks" if not problems else f"{len(problems)} leak(s)")
            return 0 if not problems else 1

        if arguments.command == "start":
            print(start(out, arguments.item))
            return 0

        if arguments.command in {"stop", "abandon"}:
            why = getattr(arguments, "why", "")
            print(finish(out, arguments.item, arguments.command, why))
            return 0

        if arguments.command == "status":
            open_item, finished = state(out)
            everything = known_items(out)
            print(f"reviewed {len(finished)} of {len(everything)}")
            if open_item:
                minutes = (time.time() - open_item["at"]) / 60.0
                print(f"open     {open_item['item']} for {minutes:.1f} minutes")
            return 0

        if arguments.command == "ingest":
            payload = ingest(out)
            records_module.write_json(arguments.output, payload)
            for arm, entry in sorted(payload["arms"].items()):
                median = entry["median_minutes"]
                shown = f"{median:.1f} min" if median is not None else "unmeasured"
                print(f"{arm:13s} {entry['items_reviewed']:3d} item(s)  {shown}")
            print(f"\nwritten to {arguments.output}")
            return 0
    except ReviewError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
