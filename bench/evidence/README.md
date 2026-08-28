# Captured incident evidence

What was observed of the running pinned application, for the change requests
whose premise is something that happened. An incident change request that
states its defect only in prose asks the agent to take the author's word for
it; these are the transcripts and logs it can read instead.

This is **input**, not ground truth. Unlike `bench/checks/`, every arm renders
it and the agent sees it. The same bytes go to every arm — the content is
fixed, and only the framing differs, which is the thing the experiment varies.
A test asserts that nothing here names an invariant or a hidden check.

Nothing in this directory is written by hand. `make evidence` reproduces each
incident against the running application and records what it saw, together with
the commit it was captured against, the JDK, and the exact requests that
produced it. `make bench-validate` fails if a change request's evidence was
captured against a commit other than the current pin, so it cannot quietly
describe a version of the application nobody is looking at.

Capturing needs the stack up (`make stack-start`); verifying a change request
does not. See `bench/VERIFICATION.md`.
