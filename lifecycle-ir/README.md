# Lifecycle IR

The canonical representation of a software change: five typed structures and, more to
the point, the references between them. Version `0.1.0`.

The structures themselves are a composition of standards that already exist. What is
new here is the linkage — every clause of intent is bound to the constraints that
bound it, the transformations that realise it, the evidence that discharges it and the
ledger entry that says who did it — and the fact that the linkage is checkable. A
bundle whose five documents are individually well formed but do not refer to each
other is not a lifecycle representation; the validator is what says so.

## The five structures

| Structure | Schema | Records | Bound to |
|---|---|---|---|
| Intent Graph | `schemas/intent-graph.schema.json` | Goals, actors, behaviors, acceptance conditions, exclusions, open questions | OpenAPI and AsyncAPI documents by JSON Pointer; acceptance conditions name executable checks |
| Constraint Graph | `schemas/constraint-graph.schema.json` | Security, privacy, architecture, performance, compatibility and cost boundaries; risk class and autonomy tier | Rego or Cedar policy modules; quantitative thresholds |
| Transformation Plan | `schemas/transformation-plan.schema.json` | Components, addressed code changes, deployment transactions, rollback, IR-to-IR delta | tree-sitter node queries, OpenRewrite recipes, Sigstore signatures, JSON Patch |
| Evidence Graph | `schemas/evidence-graph.schema.json` | Tests, analyses, runtime observation, review and build results | SARIF for static analysis, OpenTelemetry for runtime, JUnit for tests |
| Provenance Ledger | `schemas/provenance-ledger.schema.json` | Principals, and an ordered chain of what each did, decided or approved | in-toto and SLSA attestations, SPDX or CycloneDX bills of material, Sigstore |

A sixth schema, `schemas/bundle.schema.json`, describes the manifest that binds one
change request's five documents together, and `schemas/common.schema.json` holds the
identifier grammars they share.

## Identifiers

Every addressable node has an identifier of the form `<kind>:<slug>`, where the kind
is one of `actor`, `goal`, `behavior`, `acceptance`, `exclusion`, `question`,
`constraint`, `component`, `edit`, `deployment`, `rollback`, `evidence`, `entry`,
`principal`. The kind prefix is what makes a reference typed: a field can declare
which kinds it accepts, and the validator can check that the target is one of them.
Identifiers are unique across a whole bundle, not merely within a document.

## The cross-references

This table is the specification of the linkage. It is also the validator's reference
table — `lcir/model.py` holds it in executable form, and adding an edge type to the IR
means adding a row there.

| Reference | Resolves to | Meaning |
|---|---|---|
| `intent_graph.goals.stakeholders` | actor | goal is held by an actor |
| `intent_graph.behaviors.satisfies` | goal | behavior realises a goal |
| `intent_graph.behaviors.actors` | actor | behavior involves an actor |
| `intent_graph.acceptance_conditions.verifies` | behavior, goal | acceptance condition decides a goal or behavior |
| `intent_graph.exclusions.scopes` | behavior, goal | exclusion bounds a goal or behavior |
| `intent_graph.open_questions.blocks` | acceptance, behavior, goal | open question blocks an intent node |
| `constraint_graph.constraints.applies_to` | acceptance, behavior, goal | constraint bounds an intent node |
| `transformation_plan.implements` | acceptance, behavior | plan realises an intent clause |
| `transformation_plan.respects` | constraint | plan is bounded by a constraint |
| `transformation_plan.components.depends_on` | component | component depends on a component |
| `transformation_plan.code_changes.component` | component | code change edits a component |
| `transformation_plan.code_changes.implements` | acceptance, behavior | code change realises an intent clause |
| `transformation_plan.code_changes.respects` | constraint | code change is bounded by a constraint |
| `transformation_plan.deployment_changes.depends_on` | edit | deployment change ships a code change |
| `transformation_plan.rollback.reverses` | deployment, edit | rollback undoes a transformation |
| `evidence_graph.evidence.discharges` | acceptance, behavior, constraint | evidence discharges an intent clause or constraint |
| `evidence_graph.evidence.covers` | deployment, edit | evidence was observed over a transformation |
| `evidence_graph.evidence.derived_from` | evidence | evidence is derived from other evidence |
| `provenance_ledger.entries.principal` | principal | entry records who acted |
| `provenance_ledger.entries.previous` | entry | entry names its predecessor in the chain |
| `provenance_ledger.entries.input_nodes` | any node | entry consumed an IR node |
| `provenance_ledger.entries.covers` | deployment, edit, rollback | entry produced or executed a transformation |
| `provenance_ledger.entries.attests` | evidence | entry vouches for evidence |
| `provenance_ledger.entries.approval.approver` | principal | approval names the deciding principal |
| `provenance_ledger.entries.approval.subjects` | any node | approval is about an IR node |

## What the validator checks

Beyond per-document schema validity, across a bundle:

- **Identity** — identifiers are unique across the bundle.
- **Resolution** — every reference resolves to a node the bundle defines, and to a node
  of a kind the table above permits.
- **Headers** — every document declares the same IR version and change request as the
  manifest, and sits in the manifest slot matching its own declared kind.
- **Ledger chain** — sequence numbers are contiguous from one, and each entry after the
  first names the entry before it.
- **Autonomy tier** — a risk class assigning tier L2 or L3 obliges the ledger to carry
  an approval entry at that tier. A change that needs a human decision is not complete
  without a record of one.
- **Check agreement** — evidence that names an executable check must name the check its
  acceptance condition names.
- **Acyclicity** — component dependencies and evidence derivation do not run in circles.

Traceability gaps are reported as warnings rather than errors, because a bundle in
flight is legitimately incomplete: an acceptance condition with no passing evidence, a
must-constraint nothing discharges, a transformation no ledger entry accounts for, a
question still open. `--strict` makes them fatal. The same counts are what the
governance completeness measures in `eval/` will be computed from.

## Using it

```sh
make schemas                                              # the whole example suite
python lifecycle-ir/validate.py validate <bundle-dir> --strict
python lifecycle-ir/validate.py validate <document.json>
python lifecycle-ir/validate.py report <bundle-dir>       # traceability summary
```

## Examples

- `examples/change-request/CR-014/` — one change request expressed fully in IR: an
  incident-driven per-owner rate limit on visit creation in the target application. It
  is deliberately complete, exercising every reference in the table above, and it is
  what `make schemas` validates in strict mode.
- `examples/valid/` — a minimal well-formed instance of each schema, drawn from a
  smaller change request. Together they also form a coherent bundle, one still in
  flight: validating that directory reports two traceability warnings and no errors.
- `examples/invalid/` — one instance per schema that must be rejected, each listed in
  `examples/invalid/expectations.json` with the rule it violates and the message the
  validator is expected to produce.
