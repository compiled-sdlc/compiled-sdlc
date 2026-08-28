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

Status: the IR schemas, their validator, and the benchmark harness are in
place; the four arms are not. No experimental results have been produced yet;
none are reported here or anywhere else in the repository until `eval/`
computes them from recorded runs.

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
invariant was violated. A cell the apparatus could not complete — a rate limit,
an exhausted balance, a timeout — is recorded as aborted with the class of
failure, and is never counted as a failure of the agent. The matrix is
resumable: a cell with a terminal record is skipped, so an interrupted run is
continued by invoking the runner again.

## Reproduction

Nothing generated is committed. Every number, table, and figure is rebuilt from
recorded run data:

```sh
make bench-setup   # clone the target application at its pinned commit
make bench-plan    # list the cells a run would cover, and which are still pending
make bench         # execute the change-request set across the four arms
make eval          # recompute every metric and figure from runs/
```

Run telemetry is written as JSONL under `runs/`, which is not tracked.

## License

Apache-2.0. See [LICENSE](LICENSE).
