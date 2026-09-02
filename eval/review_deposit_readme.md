# The review-time study

Four kinds of thing are here, and they are not interchangeable. Two of them
describe the study and two of them *are* the study.

| File | What it is |
|---|---|
| `REVIEW_PROTOCOL.md` | The process, described in the third person: how the sample was drawn, how concealment was enforced, what the timing rules were and why. Written before the study and revised as a design document. |
| `HOW-TO-REVIEW.md` | **The instrument as administered** — the sheet the reviewer actually worked from, verbatim. It is evidence, not documentation: it is not edited to match anything, including the protocol description above. Where the two differ, this one is what happened. |
| `key.json` | The mapping from opaque item name to run, protocol and repetition, plus the salt and the sampling seed. Published because without it nobody can check that the concealment held or that the sample was drawn by the stated rule. |
| `timings.jsonl` | The raw start/stop/abandon events, one line each, in the order they were recorded. |
| `review-times.json` | The ingested result: per-protocol median and interquartile range, items reviewed, items abandoned. This is what the evaluation reads. |
| `packet/` | The concealed items themselves, one directory each, holding the change request as the reviewer saw it (`request.md`, identical across protocols for a given change request) and the diff (`change.patch`, with the protocol's own artifacts removed). |

## How to check the study rather than take it on trust

The sample was drawn by rule, not by choice: for each protocol, on each of six
change requests spanning all five difficulty classes, the lowest-numbered
repetition was selected regardless of whether it verified. `key.json` lets you
confirm that — twenty of the twenty-four selected items verified and four did
not, which is what an outcome-blind rule produces.

Concealment can be checked the same way: nothing in `packet/` names a protocol,
and change-request identifiers are redacted from the diffs, because seeing one
would tell the reviewer they had met that change before under another protocol.

## What the study does not establish

One reviewer, who is also the author, timed six items per protocol. The ranges
overlap across all four protocols. It is reported as an exploratory sensitivity
analysis and never as part of the primary measure, and the paper says so.
