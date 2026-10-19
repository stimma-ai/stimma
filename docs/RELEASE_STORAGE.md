# Release storage retention

The `Release storage cleanup` workflow runs daily at 08:23 UTC:

- Alpha artifacts are removed; the channel is retired.
- Canary artifacts expire after 14 days. The latest three versions per platform
  and every version referenced by a live update/download feed are always kept.
- Beta artifacts expire after 90 days. The latest version per platform and every
  version referenced by a live update/download feed are always kept.
- Production artifacts are kept indefinitely. Sandbox artifacts and release notes
  are outside this cleanup's scope.

All artifacts in a platform/version group must exceed the age limit. Grouping
includes version directories, legacy version aliases, platform-root Electron
archives, installers and blockmaps. Unknown filenames are preserved and reported.
The job checks JSON, Electron YAML, and signed headless feed envelopes. Missing,
malformed or dangling feeds stop cleanup; changing feed ETags stop deletion.

Run through the project CLI with the same R2 environment variables as release
publication (`R2_BUCKET`, `R2_S3_ENDPOINT`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`):

```sh
tools/stimma test release-cleanup
tools/stimma releases cleanup --report cleanup.json
tools/stimma releases cleanup --apply --report cleanup.json
```

Manual workflow dispatch defaults to a dry run. Set its `apply` input to `true`
to delete eligible objects. Scheduled runs apply the policy automatically.
The workflow uses existing repository R2 variables and secrets; it requires no
additional credentials. It can only run on `main` and serializes cleanup runs.

Each run uploads a JSON report retained for 90 days. It records candidates,
protected feeds, preserved unknown keys, successful deletions and errors. Apply
mode re-lists the bucket before deletion, checks feed ETags before each batch,
and verifies remaining feed targets and the production inventory afterward.
