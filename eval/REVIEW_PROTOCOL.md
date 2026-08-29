# Review-time study protocol

`T_human` is the third term of SALC and the only one not read off a machine:

    SALC = (C_model + C_tools + lambda * T_human) / N_verified

Until it is measured, every rate `lambda` gives the same answer and the metric
rests on model cost alone. This is how it gets measured without the measurement
being worth less than the number it produces.

## What is being measured

**How long a competent reviewer takes to decide whether a change is fit to
merge.** Not whether they are right — correctness is already settled by the
hidden acceptance checks, and a reviewer's verdict is not evidence about the
change. The claim the study supports is narrow and stated as such: *reviewing
what this arm produced took this long.*

## Sample selection

One cell per (change request, arm). The seed is the lowest one whose cell
completed, so the choice is a rule rather than a judgement and does not depend
on the outcome. That gives a fully crossed design — every arm is reviewed on
every change request — so arm and change request cannot be confounded, and a
reviewer's warm-up on a given change request is spread evenly across arms.

Aborted cells are not sampled: they measure nothing about any arm. Cells that
completed but failed verification **are** sampled. Excluding them would measure
the review time of successes only and quietly flatter whichever arm fails more
expensively — the review cost of a bad change is exactly the cost the metric is
supposed to capture.

## Concealment

The reviewer must not know which arm produced a change, or the result measures
their expectations. Four things are done, all of them in code rather than by
instruction:

1. **Opaque items.** Each item is named by a digest of its run id and a salt
   held only in the key. Nothing in a packet names an arm, a change request
   file, or a seed.
2. **Arm artifacts are excluded from the diff.** The IR arms write a bundle into
   the workspace; the compressed arm writes a minified change request. Leaving
   those in the diff would identify the arm in the first line. The packet
   carries only what the run did to the *application*.
3. **One rendering of the request.** Every item states the work in the same
   prose form, built from the change request's own brief — never from the arm's
   presentation of it. The framing is the independent variable and must not
   reach the reviewer.
4. **Shuffled order,** by the sampling seed, so consecutive items are not the
   same change request across arms in a fixed rotation.

`review.py verify` re-reads every generated packet and fails if any arm name,
artifact path, or run identifier appears in it. Run it before handing the
packet over; a leak invalidates the study, not just the item.

## Timing capture

Timestamps, not self-report. The reviewer opens an item, works, and closes it:

    make review-start ITEM=<item>
    make review-stop  ITEM=<item>

Each writes a line to `data/review/timings.jsonl`. Rules that make the numbers
mean something:

- **One item at a time.** Starting an item while another is open is refused.
- **Interruptions are discarded, not paused.** A reviewer who breaks off
  abandons the item (`review-abandon`) and it is dropped from the sample rather
  than contributing a wall-clock time that includes lunch.
- **A stated ceiling.** An item still open after 45 minutes is treated as
  abandoned. Without a ceiling one forgotten browser tab dominates every median.
- **No re-reviewing.** A second start on a completed item is refused: the second
  reading of the same change is a different task.

## Output

`review.py ingest` joins timings to the key and writes
`data/review-times.json`: per arm, the number of items reviewed, the median
minutes and the interquartile range, and the items abandoned with the reason.
Medians and IQR, never means — the same reason the cost figures use them.

`make eval` reads that file when it exists and uses each arm's median as its
`T_human`. When it does not exist, the term stays unmeasured and the report
says so rather than substituting a zero.

## What this does not establish

One reviewer is one reviewer. A single-reviewer study measures how long *that*
person took, and the manuscript reports it that way — as a measured input to
the metric with its n stated, not as a general claim about review effort. More
reviewers would license a stronger claim and are out of scope here.
