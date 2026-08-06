# Production Screenplay Import Smoke

`.github/workflows/production-screenplay-smoke.yml` is a manual-only
(`workflow_dispatch`) GitHub Actions workflow that verifies a real screenplay
import against the deployed Render service, twice, to confirm the import is
idempotent (the second run creates no duplicate scenes or shots). It requires
typing an explicit confirmation string and an existing, empty, isolated
project ID - it never runs automatically and never touches an unconfirmed
project.

## Why the screenplay secret is split into two parts

The workflow needs the screenplay content available to the job without ever
committing it to the repository, so it's stored as a base64-encoded GitHub
repository secret and decoded at runtime. GitHub enforces a per-secret size
limit; a full-length screenplay's base64 encoding can exceed it, which fails
the workflow with `"Value is too large."` before the job even starts.

To support screenplays too large for one secret, the workflow accepts an
optional two-part split, checked in this order:

1. **`PRODUCTION_SMOKE_SCREENPLAY_B64`** - if this secret exists, it is used
   exactly as before. Nothing changes for screenplays that already fit in one
   secret.
2. **`PRODUCTION_SMOKE_SCREENPLAY_B64_PART1`** and
   **`PRODUCTION_SMOKE_SCREENPLAY_B64_PART2`** - used only when the single
   secret is absent. The two parts are concatenated (`PART1 + PART2`) into
   one base64 string, and only then decoded. Decoding, empty-result
   validation, and every error message are identical to the single-secret
   path - splitting only changes how the encoded text reaches the job, not
   how it's validated or used afterward.

The reconstruction and decode logic lives in
`scripts/materialize_production_screenplay_secret.py` (previously an inline
shell heredoc in the workflow file itself), so it has real unit test coverage
in `tests/test_materialize_production_screenplay_secret.py` instead of only
being checkable by reading the YAML.

## How to generate PART1 and PART2 locally

1. Base64-encode the screenplay file exactly as you would have for the single
   secret:

   ```bash
   base64 -w0 screenplay.txt > screenplay.b64
   ```

   (macOS: `base64 -i screenplay.txt -o screenplay.b64`, since macOS `base64`
   doesn't support `-w0` - the output is already unwrapped there.)

2. Check whether it fits under GitHub's secret size limit. If it does, just
   set it as `PRODUCTION_SMOKE_SCREENPLAY_B64` and skip the rest of this
   section.

3. If it's too large, split the base64 text into two parts at the halfway
   point (splitting base64 text anywhere is safe - it's just characters,
   there's no alignment requirement):

   ```bash
   total=$(wc -c < screenplay.b64)
   half=$(( (total + 1) / 2 ))
   split -b "$half" screenplay.b64 screenplay-part-
   # produces screenplay-part-aa (PART1) and screenplay-part-ab (PART2)
   ```

4. Set the two GitHub repository secrets from the resulting files (via the
   GitHub UI, or `gh secret set` from a trusted machine - never paste secret
   values into a shell history or a committed file):

   ```bash
   gh secret set PRODUCTION_SMOKE_SCREENPLAY_B64_PART1 < screenplay-part-aa
   gh secret set PRODUCTION_SMOKE_SCREENPLAY_B64_PART2 < screenplay-part-ab
   ```

5. Delete the local `screenplay.b64` and `screenplay-part-*` files once the
   secrets are set - they contain the full screenplay content in plain text.

## Security guarantees (unchanged)

- The workflow only ever runs on manual dispatch with an explicit
  confirmation string; it is never triggered by a push, pull request, or
  schedule.
- Screenplay content, decoded bytes, and secret values are never printed,
  echoed, or written to any log. The workflow step that materializes the
  file redirects nothing to stdout, and
  `materialize_production_screenplay_secret.py`'s only failure-path output is
  a generic, content-free error message (see
  `test_error_output_never_contains_screenplay_or_secret_content` in
  `tests/test_materialize_production_screenplay_secret.py`).
- The materialized screenplay file is written with `umask 077` (owner-only
  permissions) and is always removed at the end of the job (`if: always()`),
  whether the job succeeds or fails.
- The only artifact ever uploaded is a count-only JSON result
  (`production-smoke-result.json`) - never the screenplay itself.
