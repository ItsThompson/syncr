# syncr Database Schema

This page is the schema overview `docs/prd.md` section 1 deferred. It describes what the
migrations in `packages/syncr-api/alembic/versions` build and why the schema is shaped the way
it is. It is a reading, not a snapshot: the migration chain is the authority for column-level
detail.

The chain is forward-only with a single head. The current head at the time of writing is
`sr_deploy_03_operation_session`; run `just migration-heads` to see the head now. Migrations
run as a one-shot between image pull and service start, never at application startup, so a boot
either comes up ready or says why not on `/readyz`.

## The tenancy rule

Every table that holds a user's plan carries a non-null `tenant_id`, from the first migration
that creates any table. The scope is structural: a shared mixin produces the column on every
scoped model, so it cannot be forgotten and cannot be nullable. There is no "unscoped row"
state for a query to reason about.

A tenant holds exactly one user, permanently. syncr is not a team calendar, so onboarding
another person means another independent tenant rather than another user inside one. That is
why no scoped table carries a `user_id`: there is no second user for a row to belong to, so a
user dimension would only be a place for rows to disagree.

Row-level security is not enabled. Application-level scoping plus a test that inspects
generated SQL gives the same guarantee while one tenant has nothing to leak between, and every
composite index leads with `tenant_id`, so turning RLS on later needs no re-indexing.

## Identity tables

Four tables establish identity rather than hold a plan, and each exemption from the scoped
rules is answerable:

| Table | Why it sits outside the scope |
|---|---|
| `tenants` | It is the scope. Its own `id` is what every other table's `tenant_id` references. |
| `users` | Read by email at sign-in, before any tenant is known. It carries a unique `tenant_id`, which makes the tenant-to-user relation 1:1 and permanent. |
| `sessions` | Read by the presented credential's digest, before any tenant is known. It is the one place a principal and a scope both appear, because it stores both `tenant_id` and `user_id`. |
| `oauth_clients` | Read by client id at the token endpoint, where no session exists. Its rows are deployment configuration seeded by a migration, not per-tenant data. |

A test asserts this set is exactly these four, so a fifth table cannot quietly stop proving it
is scoped.

## Table groups

### Planning inputs

What the user declares, before any solving happens.

| Tables | Hold |
|---|---|
| `areas`, `projects` | Time budgets as floors plus shares, and the projects inside them |
| `tasks`, `habits`, `routines` | The three schedulable intent kinds |
| `day_types`, `templates`, `template_entries`, `week_patterns` | Day shapes and which day type each weekday uses |
| `preferences` | Per-Area, per-habit, and per-task placement overrides |
| `anchor_types`, `anchors` | User-declared external-anchor rules and the commitments they classify |
| `off_plan_periods` | Declared spans the plan does not touch |
| `settings`, `travel_overrides` | Grid geometry, zones, review cadence, and ranges in another zone |

### Calendar sources

| Tables | Hold |
|---|---|
| `calendar_sources` | Every source (ICS feed or Google calendar), its role, its inclusion flag, and its sync state |
| `google_credentials` | The connected Google account's encrypted refresh token, and when writes started failing |

The refresh token is stored only encrypted; an access token is never stored at all.

### Plans and solving

Everything the solve lifecycle reads and writes.

| Tables | Hold |
|---|---|
| `plan_revisions` | Adopted plans, one live revision per week |
| `pending_proposals` | A solved candidate waiting for user assent |
| `week_input_versions` | Per-week version counters; the guarded write that adopts or discards a solve compares against them |
| `pins` | Blocks the user placed by hand, which re-solves must respect |
| `week_adjustments` | Concessions a week has absorbed through answered conflicts |
| `conflicts` | Overlaps raised against the plan, open and answered |
| `block_outcomes`, `edit_events` | What happened to blocks, including the pin counterfactual the learning layer trains on |
| `verdict_events` | The verdict transitions of each week |
| `weight_sets` | Versions of solver weights published by the learning layer, one active |
| `operations`, `idempotency_keys` | Tracked async work and the keys that make approvals retry-safe |
| `promotion_declines` | Repeated pins the user declined to promote into their day shape, with the cool-off |

### Access

| Tables | Hold |
|---|---|
| `sessions` | Browser sessions: the token digest, sliding idle window, and absolute expiry |
| `oauth_grants`, `oauth_authorization_codes`, `oauth_refresh_tokens` | The Authorization Server's grants, single-use codes (stored digested), and rotating refresh tokens |

How credentials move through these tables is [authorization.md](authorization.md). How clients
reach the routes that read and write everything above is the API reference,
[api.md](api.md).
