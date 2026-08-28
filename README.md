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
| `bench/` | Target-application pin, executor pin, change-request set, hidden acceptance tests |
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

## The four arms

An arm decides how a change request is represented, and nothing else. The model,
the tool set, the three budgets, the workspace, the verification and the record
are identical for all four, so a difference in what they cost is a difference
their representation has to account for.

| Arm | The change request arrives as | Edits are |
|---|---|---|
| `baseline` | Prose in the prompt | Free-form, with the build output as feedback |
| `lcir` | A typed Lifecycle IR bundle in the workspace | Addressed operations, stated as a transformation plan before they are made |
| `lcir_no_ast` | The same typed bundle | Free-form |
| `compressed` | One minified line, keys abbreviated | Free-form |

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
   into whatever artifacts that arm gives an agent.
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

## Reproduction

Nothing generated is committed. Every number, table, and figure is rebuilt from
recorded run data:

```sh
make bench-setup   # fetch the target application at its pin, then build and start it
make calibrate     # check every hidden check is red before the change and green after
make bench-plan    # list the cells a run would cover, and which are still pending
make bench         # execute the change-request set across the four arms
make eval          # recompute every metric from runs/
```

Run telemetry is written as JSONL under `runs/`, which is not tracked.

## License

Apache-2.0. See [LICENSE](LICENSE).
