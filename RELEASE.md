# Publishing a release

The paper's availability statement promises two things: the repository and a
data deposit. The repository is published by tagging. **The data deposit is not
in the repository** — it is 78 MB of run records — and has to be attached to the
release by hand. Until that is done the availability statement promises
something that does not exist, and the paper must not be submitted.

## Build the deposit

```sh
make eval                     # ensure data/eval-summary.json and figures/ are current
bash infra/build_deposit.sh   # sanitizes runs/, assembles data/deposit/, writes the ledger
cd data && zip -qr compiled-sdlc-data-<version>.zip deposit && cd ..
```

`infra/build_deposit.sh` refuses to finish if any run record still carries an
absolute path, a username, a hostname, a private address, an e-mail address or
anything credential-shaped. Model and executor identifiers are deliberately left
in: they are the apparatus, and an archive that hid them could reproduce
nothing.

## Publish

1. Tag the final state and push the tag.
2. Create a GitHub release from that tag. The Zenodo integration mints a new
   version under the existing concept DOI when a release is published; the
   concept DOI does not change, so the paper's citation stays correct.
3. Attach `data/compiled-sdlc-data-<version>.zip` to the Zenodo record, so the
   deposit is archived alongside the repository snapshot.
4. Check the new version's landing page lists both the source archive and the
   data archive before considering the availability statement true.

## What the statement promises

Keep these in step. The statement names, in the deposit: sanitized run records
for every executed cell, the evaluation summary, the figures, the calibration
record, the review timings and key, the cache-neutral and rate-sweep tables, and
the exclusion ledger. If any of those is not in the archive, either add it or
remove it from the statement.

## Current state

- `v1.1.0` is tagged and pushed.
- The deposit is built and zipped, and has not been uploaded.
- The concept DOI `10.5281/zenodo.22215075` currently resolves to `v1.0.0`,
  which contains the repository snapshot only.
