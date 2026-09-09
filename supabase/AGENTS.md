# Supabase Migration Guide

## Scope

`supabase/` is the forward-only PostgreSQL schema boundary for the staged SaaS
surface. Auth bootstrap precedes the migrations in this directory.

## Structure

`migrations/` contains timestamp-prefixed SQL applied lexicographically by the
Compose bootstrap after `docker/stage3/001-auth-schema.sql`.

## Where To Look

| Task | Location | Notes |
| --- | --- | --- |
| Tenant/account foundation | `migrations/20260816*`, `20260820*` | Ordered schema, RLS, routines, and Personal Lab registry. |
| Billing/widget boundary | `migrations/20260825120000_mvp_personal_lab_billing_widget.sql` | Ledger, publication, quota, and service-role routines. |
| Schema tests | `tests/supabase/`, `tests/api/*_postgres.py` | Static contracts plus disposable Postgres behavior. |

## Conventions

- Keep data-changing migrations transactional where possible and repeatable
  where policy/trigger creation requires it. Do not add down-migrations.
- Exposed tables enable and force RLS. Revoke broad privileges, then grant only
  the intended `authenticated` or `service_role` access.
- Keep privileged routines/session storage in the private schema. Enforce
  ownership, lifecycle, immutable audit/ledger, and quota invariants in SQL.
- Preserve tenant, workspace, Personal Lab, billing, publication, audit, and
  quota data. Operational rollback is a runtime/traffic switch, not schema
  reversal or destructive cleanup.
- Maintain conservative foreign-key deletion behavior and atomic failure
  rollback. The quota reservation contract caps 500 committed/reserved messages.

## Anti-patterns

- Never add `DROP TABLE`, `TRUNCATE`, broad deletes, destructive type changes, or
  a second bootstrap path to make a migration easier to apply.
- Do not bypass RLS/private-schema/service-role boundaries or authorize from
  browser-controlled identifiers.
- Do not test only static SQL. Every schema change needs disposable Postgres
  coverage for ordering, RLS/permissions, preservation, and rollback/concurrency.

## Verification

Use `tests/supabase/` for schema contracts and the API `*_postgres.py` tests for
production store behavior. Apply the complete stack in a disposable database;
never experiment against operator or production data.
