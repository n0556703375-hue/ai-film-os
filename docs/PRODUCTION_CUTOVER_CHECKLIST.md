# Production PostgreSQL Cutover Checklist

This is the operator checklist for switching the deployed service from SQLite
to PostgreSQL. It exists so the cutover can be executed later with one
explicit human approval, using tooling that is already built and tested -
not so it can be executed automatically. No step here runs itself.

Related tooling:
- `scripts/production_cutover_check.py` - read-only prerequisite check (see below).
- `python -m app.database.migration_preflight` - read-only SQLite source audit.
- `python -m app.database.sqlite_backup_verification` - read-only backup verification.
- `python -m app.database.cutover_readiness` - composed, rollback-only readiness gate.
- `python -m app.database.postgres_import_commit` - the one command that persists data into PostgreSQL.
- `ENABLE_POSTGRESQL` / `DATABASE_URL` - the runtime activation gate (`app/database/backend.py`).

## PRE-CUTOVER

- [ ] CI is green on `main`.
- [ ] Test Gate is green on `main`.
- [ ] The latest Render deploy is green.
- [ ] `ENABLE_POSTGRESQL` is still disabled in the production environment.
- [ ] The target Render PostgreSQL instance exists and is reachable.
- [ ] `DATABASE_URL` has not yet been switched to point at it.
- [ ] A SQLite backup of the production database has been taken and verified
      (`python -m app.database.sqlite_backup_verification --confirm-read-only`
      reports `"status": "verified"`).
- [ ] `python -m app.database.migration_preflight --confirm-read-only` reports
      `"status": "ready"` against the production SQLite source.
- [ ] `python -m app.database.cutover_readiness --confirm-non-destructive`
      reports `"status": "ready"`.

## CUTOVER

- [ ] Enable PostgreSQL: set `ENABLE_POSTGRESQL=true` in the production environment.
- [ ] Set `DATABASE_URL` to the target PostgreSQL instance.
- [ ] Restart the web service so the new configuration takes effect.
- [ ] Run `python -m app.database.postgres_import_commit --confirm-persistent-import IMPORT_TO_EMPTY_POSTGRES`
      and confirm the result reports `"status": "imported"` and `"sequences_realigned": true`.
- [ ] Verify sequence alignment: confirm the import result's `sequences_realigned`
      flag is `true` (the commit command realigns every serial-id table's
      sequence past its imported max id automatically - this is not a
      separate manual step, only a confirmation).
- [ ] Verify application startup: the service starts cleanly against the new
      PostgreSQL target with no schema-validation errors.

## POST-CUTOVER

- [ ] `GET /health` reports `{"status": "ok"}`.
- [ ] A minimal create/read/update pass through the running application
      succeeds (for example: create a project, read it back, update it).
- [ ] A screenplay import against the deployed service succeeds
      (`scripts/deployment_smoke.py --execute-import`).
- [ ] Scene count after import matches expectations for the imported screenplay.
- [ ] Shot count after import matches expectations for the imported screenplay.
- [ ] Re-running the same import is idempotent (no duplicate scenes/shots are
      created; `scripts/deployment_smoke_idempotency.py` or a second
      `deployment_smoke.py --execute-import` run against the same project
      confirms this).
- [ ] No writes crossed project boundaries during any of the above (production
      snapshot checks in `deployment_smoke.py` already assert this on every run).
- [ ] Video queue sanity: a queued video job can still be created and its
      status polled through `/api/video-generation/jobs/{job_id}/status`.
- [ ] Rollback decision: if any check above fails, the documented rollback is
      to set `DATABASE_URL` back to empty (or `ENABLE_POSTGRESQL=false`) and
      restart, which returns the service to the verified SQLite source - no
      data was deleted or replaced during cutover, so this is safe. Record
      whether rollback was needed and why.

## `scripts/production_cutover_check.py`

A read-only helper that reports PASS/FAIL for the mechanical prerequisites
above (not the CI/Render/manual-review items, which require a human to
confirm). It never modifies data, never writes to production, and never
performs a migration - it only checks environment variables, file presence,
database connectivity, and the health endpoint, then exits non-zero if
anything it checked is not ready.

```
PYTHONPATH=. python3 scripts/production_cutover_check.py [--base-url URL]
```

Checks performed:
1. Required environment variables (`FILM_OS_DB`, `FILM_OS_BACKUP_DB`) are set.
2. `ENABLE_POSTGRESQL` state (reported, not asserted - both `true` and `false`
   are valid depending on when in this checklist you run it).
3. `DATABASE_URL` is present and uses a PostgreSQL scheme.
4. PostgreSQL connectivity: a real, read-only `SELECT 1` probe.
5. The SQLite source file exists on disk.
6. The SQLite backup file exists on disk.
7. The deployed `/health` endpoint responds with `{"status": "ok"}` (only if
   `--base-url` is given).

Running it today, with no environment changes, is expected to report several
`FAIL` lines (no `DATABASE_URL`, no backup configured, no `--base-url`) - that
is the correct, safe pre-cutover state, not a bug.

## Explicit approval boundary

Nothing in this repository executes any step under **CUTOVER** automatically.
Every command listed there requires a human to run it deliberately, with
explicit flags (`--confirm-persistent-import IMPORT_TO_EMPTY_POSTGRES`, etc.)
that exist specifically so the destructive-adjacent step cannot happen by
accident. This checklist and `production_cutover_check.py` exist to make that
one approval fast and low-risk to give, not to remove the need for it.
