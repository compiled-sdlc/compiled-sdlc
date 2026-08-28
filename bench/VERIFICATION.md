# What verification does, and one thing it cannot do yet

Every change request in this set is verified by module tests: the module's own
suite must still pass, the hidden acceptance checks must pass, and no `must`
invariant may be violated. None of that needs the application running, so every
cell of the run matrix is a JDK and a Maven build and nothing else.

## The gap: the stack runner boots the pin, not the workspace

`infra/stack.py` starts the application from `bench/target` — the pinned
checkout — using the jars built there. It has no notion of a run's workspace.
A run, by contrast, happens in a fresh clone of the pin that the agent then
changes.

So if a change request were to declare `needs_stack: true` today,
`verify.run_stack()` would bring up **the unmodified application** and any check
that exercised it over the wire would be testing the pin rather than the agent's
change. Such a check would pass or fail for reasons entirely unrelated to the
run, and — worse — it would look like a verified success.

Nothing in the current set declares `needs_stack: true`, and
`tests/test_calibration.py` asserts that a request's declaration matches what
calibration recorded, so the gap is not reachable by accident. The
`live_stack_incident` value in the change-request schema's `difficulty`
vocabulary is defined and deliberately unused.

## What closing it would take

1. `stack.py` accepts a checkout to boot from, rather than always
   `locks.target_checkout()`, and builds that checkout's jars first.
2. Port isolation, so a stale stack from another cell cannot answer a probe and
   be mistaken for this one.
3. `verify.run_stack()` passes the run's workspace through, and
   `infra/calibrate.py` starts the same stack when calibrating such a request.
4. A readiness wait that covers service discovery, not just health. Health is
   not sufficient: the services report healthy before the gateway can resolve
   them through the registry, and a request made in that window fails with a
   500 that has nothing to do with the change. `infra/capture_evidence.py`
   works around this by polling the gateway until it answers.

Until all four exist, a live-stack change request cannot be verified honestly,
which is why the set has none.

## Evidence is a different thing

`bench/evidence/` holds runtime observations captured from the running pinned
stack by `infra/capture_evidence.py`. That evidence is **input**: it is handed
to the agent, in every arm, as the account of an incident it is being asked to
address. It is not verification and it is not ground truth. Capturing it needs
the stack; verifying the change does not.
