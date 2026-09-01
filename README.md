# The Compiled SDLC

A dual-representation lifecycle protocol for agentic software delivery: a typed,
versioned, verifiable **Lifecycle Intermediate Representation** is the canonical
control plane for a software change, and executable artifacts, assurance
evidence, and human-readable views are generated projections of it.

This repository holds the research code for that protocol and for the four-arm
experiment that measures it. The primary measurement is **success-adjusted
lifecycle cost** — total model, tool, and weighted human-review cost across all
attempts, divided by the number of change requests that pass hidden acceptance
tests without violating a `must` invariant.

Status: the IR schemas, their validator, the benchmark harness and the four
arms are in place. No experimental results have been produced yet; none are
reported here or anywhere else in the repository until `eval/` computes them
from recorded runs on the full change-request set.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/), GNU make, and a JDK 17 or newer for
the target application. No containers are needed: the application is built as
plain jars and run as folder-local JVM processes. The JDK is machine-specific,
so its location is read from `JAVA_HOME` in an untracked `.env` at the
repository root rather than from the ambient path.

```sh
make scaffold        # create the virtual environment and the untracked working directories
make                 # lint, test, and run the repository hygiene audit
make schemas         # validate every Lifecycle IR example against its schema
make bench-setup     # fetch the target application at its pin and check it builds and starts
make bench-validate  # check the change-request set against its schema and the pin
make smoke           # prove the executor plumbing with one trivial run
make stack-start     # run the target application locally; stack-status, stack-stop
make help            # list every target
```

Everything the experiment is pinned to is in a lock file: the target
application and its build in `bench/target.lock`, the executor and the model it
runs in `bench/executor.lock`, and the prices token counts are costed at in
`eval/pricing.lock`. Nothing else in the repository names them.

## Layout

| Path | Contents |
|---|---|
| `lifecycle-ir/` | JSON Schemas for the five IR structures, example instances, validator |
| `pipelines/common/` | Shared run harness: budgets, telemetry capture, arm interface |
| `pipelines/baseline/` | Arm A — natural-language requirements, plain-text edits, log feedback |
| `pipelines/lcir/` | Arm B — full Lifecycle IR: typed intent, structured edits, evidence, provenance |
| `pipelines/lcir_no_ast/` | Arm C — ablation: typed intent and evidence, plain-text edits |
| `pipelines/compressed/` | Arm D — aggressively minified artifacts |
| `projections/` | Generators that render human-readable views from the IR |
| `bench/` | Target-application pin, executor pin, change-request set, hidden acceptance tests, captured incident evidence |
| `eval/` | Metrics and figure generation |
| `infra/` | Repository hygiene audit and environment setup |
| `tests/` | Test suite |

## The five IR structures

| Structure | Records | Bound to |
|---|---|---|
| Intent Graph | Goals, actors, behaviors, acceptance conditions, exclusions, open questions | OpenAPI, AsyncAPI |
| Constraint Graph | Security, privacy, architecture, performance, compatibility, cost boundaries | Rego, Cedar |
| Transformation Plan | Affected components, structured code and deployment changes, rollback | tree-sitter, OpenRewrite, JSON Patch, Sigstore |
| Evidence Graph | Traceability from every requirement and invariant to the checks that discharge it | SARIF, OpenTelemetry, JUnit |
| Provenance Ledger | Principals and their versions, inputs, decisions, approvals, artifact hashes | in-toto, SLSA, SPDX/CycloneDX |

The structures are a composition of standards that already exist; what the IR
adds is the typed linkage between them, and a validator that checks it across a
whole bundle rather than one document at a time. `lifecycle-ir/README.md` states
every cross-reference the IR defines and what the validator enforces;
`lifecycle-ir/examples/change-request/CR-014/` is one change request expressed
fully in IR, exercising all of them.

## The four protocols

A protocol decides how a change request is represented and what the agent must
produce alongside the change, and nothing else. The model, the tool set, the
three budgets, the workspace, the verification and the record are identical for
all four, so a difference in what they cost is a difference the protocol has to
account for.

The four form a 2x2 — the request is prose or typed, and an addressed
transformation plan is demanded or not. The paper names them by what they vary;
the code keeps the original identifiers, and this is the mapping.

| Protocol (paper) | Identifier (code) | Request | Plan demanded |
|---|---|---|---|
| prose-free | `baseline` | Prose in the prompt | No |
| prose-min | `compressed` | One minified line, keys abbreviated | No |
| typed-free | `lcir_no_ast` | A typed Lifecycle IR bundle | No |
| typed-plan | `lcir` | The same typed bundle | Yes — addressed operations, stated before they are made |
| _prose-plan_ | — | Prose in the prompt | Yes — **designed, costed, not run** |

`prose-plan` is the missing cell of the factorial. It would separate the plan
obligation from the typing on the prose side, as `typed-free` does on the typed
side. It was not run because the remaining budget did not cover it, so every
claim about the plan obligation rests on the typed side alone.

**Repetitions, not seeds.** A cell is run three times under identical
conditions. Nothing passes a sampling seed to the model; the record's `seed`
field is the repetition index, and the paper calls it an independent repetition.

`lcir_no_ast` is the ablation: it separates what typing the intent buys from
what structuring the edits buys. Every arm is given the same content — the same
statement, the same observable behaviours, the same stated boundaries — and a
test holds them to it.

Prompt tuning is bounded and equal: each arm has the same allowance of template
revisions, recorded with the digest of its frozen template in
`bench/prompt-allowance.json`. An arm that had more attention spent on it would
win on effort rather than on representation.

After a run, the IR arms write what verification observed into an evidence
graph, record who did what in a provenance ledger, assemble and validate the
whole bundle, and render the projections in `projections/` — a user story, a
change summary and an incident note, generated from the IR rather than
maintained beside it.

## How a run works

One run is one change request, put to one arm, at one seed.

1. The run gets a fresh worktree of the target application at its pin. Nothing
   from this repository is placed in it.
2. The arm renders the change request's statement — and only its statement —
   into whatever artifacts that arm gives an agent. A change request that
   begins with an incident also carries the runtime evidence for it: HTTP
   transcripts and service logs captured from the running pinned application,
   the same bytes for every arm, placed in the worktree and referred to in each
   arm's own idiom. It is input, never ground truth.
3. The pinned executor runs headlessly in that worktree under three budgets: a
   cost ceiling it enforces itself, and a turn cap and a wall clock the harness
   enforces around it. The whole event stream is captured as it arrives.
4. Once the agent has stopped, the harness applies the ground truth the agent
   never saw: the `must` invariants, evaluated against the worktree and the
   pin, and the hidden acceptance tests, placed in the worktree only now, run,
   and removed again.
5. The run record is written: tokens in, out and reasoning, tool calls, turns,
   wall time, the cost recomputed from the captured price table, what changed
   in the worktree, and what verification decided.

A run is a verified success only if every acceptance check passes and no `must`
invariant was violated.

Two rules decide what a cell means, and they hold for the whole experiment. A
cell that spent its budget — the cost ceiling, the turn cap or the wall clock —
without finishing is a failure of the agent: the budget is a condition of the
experiment, identical for every arm. It counts against its arm and its cost
counts in the metric. A cell the API would not serve — an exhausted balance, a
rate limit, an authentication failure — measures nothing about any arm; it is
recorded as aborted with the class of failure and excluded from every column.
The matrix is resumable, so an aborted cell is picked up by invoking the runner
again.

Before any of this means anything, the change-request set is calibrated against
the pristine pin: every hidden acceptance check must fail on the unmodified
application and every `must` invariant must pass. A check that is already green
cannot tell a successful run from an agent that did nothing. `make calibrate`
does it and records the result in `bench/calibration.json`.

The evidence itself is captured, not written: `make evidence` reproduces each
incident against the running application and writes what it observed under
`bench/evidence/`, with a record of the pin it was taken against. A change
request whose evidence was captured against another commit fails validation.

Verification needs no running application — every change request is settled by
module tests. `bench/VERIFICATION.md` says why, and records the one thing this
harness cannot do yet: the stack runner boots the pin rather than a run's
workspace, so no check may be pointed at a live system.

## What the evaluation reports

**Success-adjusted lifecycle cost** — model cost plus execution cost plus
review time at a stated rate, divided by verified successes. Dividing by
successes is the point: an arm that spends twice as much and fails half as often
is not cheaper, and retries and failures show up as cost instead of averaging
away. A verified success passed the hidden acceptance checks and violated no
`must` invariant — nothing else enters that denominator. Review time is not
measured yet, so the weighted term contributes nothing; the report says so
rather than reporting it as zero review time, which would be a different claim.

**Governance completeness** — five components: whether the change was stated as
a transformation plan that validates, whether the bundle assembled, whether the
human decision the risk class demands was recorded, whether every obligation has
a passing evidence path, and whether every transformation is accounted for by
the ledger. Only the arms that produce IR can answer any of them, and that is
reported as a capability, never scored as a penalty: an arm with no IR is not
failing these checks, it has no way to take them — and no way to notice when its
own governance is incomplete. Each component reads as scored, applicable but not
recorded, or not observable; none of the three is a zero, and none of them
touches whether a change request succeeded.

**Distributions and the frontier** — median and interquartile range per arm for
cost, tokens, reasoning tokens, turns and wall time, a Pareto plot of cost
against verified success, and a per-change-request breakdown. Medians rather
than means, because run-to-run variance on this kind of work is large enough
that an average of a handful of runs says very little. Where the frontier
separates two arms by less than their own spread, the report says the ordering
is not established.

Every output is labelled by what it was computed from, and the label is decided
by the data: a run set that has not met the experiment's discipline — three
seeds per cell over the full change-request set — is labelled a pilot on every
table and every figure. There is no flag to say otherwise.

## Reproduction

Nothing generated is committed. Every number, table, and figure is rebuilt from
recorded run data:

```sh
make bench-setup   # fetch the target application at its pin, then build and start it
make calibrate     # check every hidden check is red before the change and green after
make bench-plan    # list the cells a run would cover, and which are still pending
make bench         # execute the change-request set across the four protocols
make eval          # recompute every metric and figure from runs/
make project CRS=20 SEEDS=3   # price a run before launching it
```

`make eval` reads the run records and nothing else — not the bundles a run left
beside them, not anything held in memory while it ran. Delete the figures and
the summary, run it again, and the same numbers come back. Everything it writes
lands in untracked directories: the repository carries the recipe, not the
product.

Run telemetry is written as JSONL under `runs/`, which is not tracked.

## Provenance

[PROVENANCE.md](PROVENANCE.md) maps every experiment to the outputs it produced,
gives the reproduction commands in order, records what is pinned, and states the
full run ledger — including the cells that were voided, discarded or archived,
and why.

## Citing this artifact

Archived at Zenodo. The DOI below is the concept DOI: it always resolves to the
latest version, and each release also has its own.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22215075.svg)](https://doi.org/10.5281/zenodo.22215075)

> Syed Moid. *compiled-sdlc/compiled-sdlc: v1.0.0 — The Compiled SDLC*.
> Zenodo, 2026. https://doi.org/10.5281/zenodo.22215075

## License

Apache-2.0. See [LICENSE](LICENSE).
