# Publishing a release

The paper's availability statement promises two things: the repository and a
data deposit. The repository is published by tagging. **The data deposit is not
in the repository** — it is 78 MB of run records — and has to be attached to the
release by hand. Until that is done the availability statement promises
something that does not exist, and the paper must not be submitted.

## Build the deposit

```sh
make eval        # ensure data/eval-summary.json and figures/ are current
make deposit     # sanitize, assemble, scan, and zip in one step
```

`make deposit` names the zip after the current tag, so the tag and the archive
cannot drift apart. It refuses to emit anything if any file in the assembled
archive carries an absolute path, a username, a hostname, a private address, an
e-mail address or anything credential-shaped --- the sanitizer guarantees the
run records, and this gate extends that guarantee to the derived results, the
review packet and the ledger. Model and executor identifiers are deliberately left
in: they are the apparatus, and an archive that hid them could reproduce
nothing.

## Publish

The GitHub–Zenodo auto-sync is being turned **off** first, so that publishing a
release cannot mint a source-only version. The deposit and the snapshot go up
together or not at all.

1. Confirm auto-sync is off for this repository in Zenodo's GitHub settings.
2. Tag the final state and push the tag (done: `v1.1.1`).
3. On Zenodo, open the existing record under the concept DOI and choose **New
   version**.
4. Upload **both**: the source snapshot for the tag (GitHub's
   `.../archive/refs/tags/v1.1.1.zip`) and `data/compiled-sdlc-data-v1.1.1.zip`.
5. Set the version metadata to `v1.1.1` and publish.
6. Check the new version's landing page lists both archives before considering
   the availability statement true.

## What the statement promises

Keep these in step. The statement names, in the deposit: sanitized run records
for every executed cell, the evaluation summary, the figures, the calibration
record, the review timings and key, the cache-neutral and rate-sweep tables, and
the exclusion ledger. If any of those is not in the archive, either add it or
remove it from the statement.

## Do not submit until this is done

**Gate: OPEN — the paper must not be submitted.**

The availability statement names release v1.1.1 and promises a data deposit.
Until the concept DOI `10.5281/zenodo.22215075` verifiably resolves to a version
whose files include the data archive, that promise is false.

Close this gate only after fetching the record and confirming the data archive
is listed. Then change this section to say so, and record the version DOI here
for reference.

## Current state

- `v1.1.1` is tagged and pushed.
- The deposit is built, scanned and zipped as
  `data/compiled-sdlc-data-v1.1.1.zip`, and has not been uploaded.
- The concept DOI currently resolves to `v1.0.0`, which contains the repository
  snapshot only — no run records.
