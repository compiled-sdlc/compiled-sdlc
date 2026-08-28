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

Status: the IR schemas and their validator are in place; the benchmark harness
and the arms are not. No experimental results have been produced yet; none are
reported here or anywhere else in the repository until `eval/` computes them
from recorded runs.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) and GNU make. Docker is required from
the benchmark phase onward.

```sh
make scaffold   # create the virtual environment and the untracked working directories
make            # lint, test, and run the repository hygiene audit
make schemas    # validate every Lifecycle IR example against its schema
make help       # list every target
```

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
| `bench/` | Target-application pin, change-request set, acceptance tests, invariants |
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

## Reproduction

Nothing generated is committed. Every number, table, and figure is rebuilt from
recorded run data:

```sh
make bench-setup   # clone the target application at its pinned commit
make bench         # execute the change-request set across the four arms
make eval          # recompute every metric and figure from runs/
```

Run telemetry is written as JSONL under `runs/`, which is not tracked.

## License

Apache-2.0. See [LICENSE](LICENSE).
