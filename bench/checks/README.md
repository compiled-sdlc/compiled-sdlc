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

## Every check needs a passability argument

`make calibrate` proves a check is red on the unmodified pin. It cannot prove
the check can ever go green, and nothing else in the harness can either. A check
that no correct change satisfies looks exactly like a change request every arm
failed, and the difference only becomes visible after the runs are paid for.

So a check is not finished until its change request can answer, in one or two
sentences: **by what route does a correct implementation satisfy this, and can
the test's own fixtures express that route?** Write it down when you write the
test. The question that catches most defects is the second one — whether the
fixture can put the application into the state the assertion demands.

CR-109 is the worked example. Its check required an info line carrying the
owner's identifier; the owner entity has no setter for its id, so the fixture's
owner had none, and every arm that read the identifier off the record logged
`null` and failed. Only the request path carried the identifier, which the
change request had not asked for. Four cells were spent discovering it.

## When a change request is excluded

A change request is excluded from the reported results **only** when its ground
truth is shown to be unsatisfiable — no correct implementation could pass it.
Not when an arm finds it hard, and not when the result is unwelcome.

An exclusion removes the change request for every arm and every seed. Removing
one arm's cells would be selecting on the outcome, which is the thing the whole
apparatus exists to prevent. The excluded cells are kept where they can be read
(`runs/`, out of the matrix), and the exclusion is reported with its reason, its
cell count, and what those cells cost: the money was spent and the experiment
should say so.
