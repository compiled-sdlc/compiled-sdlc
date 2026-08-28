# Hidden acceptance checks

Ground truth for the change-request set: the tests that decide whether a run
succeeded. They are tracked openly here — "hidden" means hidden from the agent,
not from the reader — and the harness places them in the workspace only after
the agent has finished, runs them, and removes them again.

Nothing in this directory may be rendered into a prompt or copied into a
workspace before a run. `pipelines/common/changerequests.py` builds the agent's
view of a change request from its statement alone, and a test asserts that no
hidden material reaches it.

Each file is written against the target application at its pin, in the style and
package of the tests already in that module, so it compiles against the module
as the agent found it.
