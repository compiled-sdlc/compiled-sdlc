# Provenance

What produced every number in the paper, and how to produce it again. Nothing
reported is transcribed by hand: each figure in the manuscript resolves through
a macro generated from `data/eval-summary.json`, which is itself computed from
the run records and nothing else.

## Experiments to outputs

| Output | Produced by | Reads |
|---|---|---|
| `runs/<CR>__<protocol>__seed<n>/record.json` | `make bench` | the pinned application, the pinned executor |
| `runs/<cell>/diff.patch`, `transcript.jsonl` | `make bench` | the same run |
| `runs/<cell>/lifecycle-ir/` | `make bench` (typed protocols only) | the run's workspace |
| `bench/calibration.json` | `make calibrate` | the change-request set, the pin |
| `bench/evidence/<CR>/` | `make evidence` | the running pinned stack |
| `data/eval-summary.json` | `make eval` | `runs/` only |
| `figures/*.png` | `make eval` | `runs/` only |
| `data/review/` (packet, key, timings) | `make review-sample`, `review-start/-stop` | `runs/` |
| `data/review-times.json` | `make review-ingest` | `data/review/` |
| `manuscript/generated/numbers.tex` | `make manuscript` | `data/eval-summary.json`, the lock files |
| `manuscript/main.pdf` | `make manuscript` | the above |

`make eval` reads the run records and nothing else — not the IR bundles a run
left beside them, not anything held in memory while it ran. Delete `data/` and
`figures/`, run it again, and the same numbers come back.

## Reproduction, in order

```sh
make setup                     # environment
make bench-setup               # clone the target application at its pin, build it
make bench-validate            # the change-request set against its schema and the pin
make calibrate                 # every hidden check red before the change, invariants green
make stack-start && make evidence && make stack-stop   # incident evidence (needs the stack)
make bench BENCH_FLAGS="--seeds 3"                     # the run matrix (billed)
make eval                      # every metric and figure
make review-sample REVIEW_FLAGS="--change-requests 6"  # the concealed review packet
make review-ingest             # per-protocol review medians
make manuscript                # regenerate numbers, build the PDF, count words
make audit                     # the repository hygiene checks
```

Only `make bench` costs money. Everything downstream of it is deterministic
given `runs/`.

## What is pinned

| | |
|---|---|
| Target application | `bench/target.lock` — repository, exact commit, build and test commands |
| Executor and model | `bench/executor.lock` — CLI version, model identifier and how it was resolved, tools, budgets |
| Prices | `eval/pricing.lock` — per-model rates with the capture date |
| Environment | `bench/environment.lock` — JDK banner, the service set, verification date |
| Prompt templates | `bench/prompt-allowance.json` — revision allowance and digest per protocol |

Every cell's record carries the hash of its instantiated prompt alongside the
hash of its template, so a prompt cannot change without the record saying so,
and the runner refuses to reuse a cell whose template digest is not current.

## The run ledger

264 cells were executed for the analysed matrix:

- **240 analysed** — 20 change requests x 4 protocols x 3 independent repetitions.
- **24 voided** for an apparatus defect (the task framing named only the first
  of two modules on cross-service change requests) and re-run. Kept in
  `runs/void-cross-service-prompt/`.

Separately, and outside that matrix:

- **4 discarded** when a change request proved unpassable by any correct
  implementation. Kept in `runs/defective-cr109-check/`.
- **40 pilot cells** taken under prompt-template revision 1, not comparable with
  what followed. Kept in `runs/pilot-revision-1/`.

Nothing is deleted. Each archive directory carries a README saying why it is
out of the matrix.

## Repetitions, not seeds

A cell is run three times under identical conditions. Nothing passes a sampling
seed to the model; the `seed` field in a record is the repetition index. The
paper calls these independent repetitions.

The one seed that does exist is the bootstrap's, recorded in
`data/eval-summary.json` under `bootstrap.seed`, so every interval in the paper
is reproducible.

## Governance figures are versioned

`GOVERNANCE_REVISION` in `pipelines/lcir/finalise.py` stamps every finalised
record. The evaluation sets aside — never averages in — any record scored under
a superseded revision. `infra/regovern.py` recomputes figures from a run's
archived bundle when the definition changes, rewriting only the judgement and
keeping what the record said before.
