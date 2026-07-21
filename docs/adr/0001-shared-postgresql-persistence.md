# ADR 0001: Shared PostgreSQL persistence

- Status: Proposed
- Date: 2026-07-21
- Related issue: #56

## Context

AI Film OS currently opens a local SQLite file through `app/database/connection.py`. This is safe for the existing single Render web service, but a separate scheduled or background Identity Drift worker would have an independent filesystem and could read or write a different database.

The roadmap requires background jobs, retry and idempotency, while the Identity Drift workflow already relies on atomic claim, stale-claim recovery, and durable result storage.

## Decision

Adopt a managed shared PostgreSQL database before enabling any separate Render cron or background worker.

SQLite remains supported for local development and tests during the transition. Production must not switch automatically: enabling PostgreSQL requires an explicit deployment change and a verified data-preservation procedure.

## Safety constraints

1. No destructive replacement of the existing SQLite database.
2. Export and validate production data before changing the production connection setting.
3. Use environment-only credentials through a database URL; never log the URL or password.
4. Keep migrations additive and repeatable.
5. Verify row counts and key relationships before and after import.
6. Preserve Identity Drift claim atomicity and stale-claim recovery semantics.
7. Keep the split-service SQLite CI guard until production is confirmed on shared persistence.
8. Roll back by restoring the prior web configuration and retained SQLite snapshot; do not delete either data source during cutover.

## Incremental implementation plan

1. Introduce a database backend boundary while retaining SQLite as the default.
2. Add PostgreSQL-compatible schema migrations and repository tests.
3. Add a read-only SQLite export and PostgreSQL import command with dry-run validation.
4. Test the migration against a disposable database and fixture data.
5. Provision managed PostgreSQL and perform an explicitly approved production migration.
6. Confirm the web service reads the migrated data.
7. Enable the bounded Identity Drift scheduled worker against the same database.
8. Remove the split-service SQLite guard only after deployment verification.

## Acceptance checks

- Web and worker use the same durable database.
- Existing projects, scenes, shots, assets, media, approval history, and continuity issues are preserved.
- Foreign-key relationships and unique constraints remain valid.
- Identity claims cannot be processed twice concurrently.
- No credentials or database URLs appear in logs or command output.
- CI covers both SQLite compatibility and PostgreSQL-specific behavior.

## Consequences

This delays scheduling the worker until shared persistence is ready, but prevents silent processing against an empty or divergent database. It also establishes the persistence foundation needed for broader production reliability work in the architecture roadmap.
