# Bootstrap the first tenant and user

## Trigger

The first deployment of a stack, immediately after migrations have been applied and
before anyone tries to sign in.

Also whenever a restored database has no account: a restore brings back whatever the
backup held, and a backup taken before this step contains no user.

## Why this is a runbook and not a screen

P0 has no sign-up flow, no invitation, and no account-creation route. Multi-user
onboarding is a later concern, and a registration screen exactly one person would ever
see is a screen not worth building or defending. So the first tenant and its one user are
created by a command against the database, and that command is documented here rather
than rediscovered by whoever deploys next.

Nothing else creates an account. A stack with migrations applied and no account answers
`401` on every domain route, which looks like a broken deployment and is in fact a
deployment nobody has bootstrapped.

## Preconditions

| Condition | How to confirm |
|---|---|
| Postgres is reachable | `just dev-infra` locally, or the stack's `postgres` service is healthy |
| Migrations are applied | `just migrate`, or `curl -s localhost:8000/readyz` reports `status: ready` |
| A password is chosen | At least 12 characters. This account is reachable from the public internet through the tunnel |

## Steps

Locally, against the database `DATABASE_URL` names:

```
just bootstrap-user owner@example.com
```

The command prompts for the password. It is never taken as an argument: an argument
appears in the shell history, in the process table while the command runs, and in any log
that records the invocation.

In the deployed stack, run it inside the api image so it uses the same
in-network `DATABASE_URL` the service does:

```
docker compose run --rm api syncr-bootstrap-user
```

That form prompts for both the email and the password. To script it, supply
`SYNCR_BOOTSTRAP_EMAIL` and `SYNCR_BOOTSTRAP_PASSWORD` in the environment. Prefer the
prompt: an exported password is a password in the shell's history file.

## What it does

One transaction, two rows:

- a `tenants` row, which is the scope every later table's `tenant_id` points at
- a `users` row holding the email, the scrypt password hash, and that tenant id

The email is stored lowercased and trimmed, which is the form sign-in compares against.
`users.tenant_id` is unique, so a second user in that tenant is rejected by the database.

## Verify it worked

Sign in. That exercises the password hash, the session table, and the cookie in one step,
which is what the account exists for:

```
curl -i -X POST https://<host>/auth/login \
  -H 'Content-Type: application/json' \
  -H 'Origin: https://<host>' \
  -d '{"email":"owner@example.com","password":"<the password>"}'
```

Expect:

- `200` with a body naming `tenantId`, `userId`, `email`, and `expiresAt`
- a `Set-Cookie` header carrying `syncr_session`, with `HttpOnly`, `Secure`,
  `SameSite=Lax`, and a `Max-Age` of the absolute session lifetime. The server, not the
  browser, decides when the session stops working: `expiresAt` in the body is the shorter,
  sliding expiry
- one log line, `accounts.sign_in.succeeded`, carrying the tenant and user ids and no
  email

Then confirm the session works and can be ended:

```
curl -s https://<host>/auth/session --cookie 'syncr_session=<the token>'
curl -i -X POST https://<host>/auth/logout --cookie 'syncr_session=<the token>' \
  -H 'Origin: https://<host>'
curl -s https://<host>/auth/session --cookie 'syncr_session=<the token>'
```

Expect `200`, then `204`, then `401`. The third call proves sign-out revoked the session
server-side rather than only clearing the cookie.

## If it does not work

| Symptom | Cause | What to do |
|---|---|---|
| `refused: the password is shorter than 12 characters` | The password is too weak for an internet-reachable account | Choose a longer one. Nothing was created |
| `the database could not be reached` | `DATABASE_URL` points somewhere else, or Postgres is down | Check the variable and the service, then re-run |
| `relation "users" does not exist` | Migrations have not been applied | `just migrate`, then re-run |
| `nothing to do: tenant ... already holds user ...` | The account exists already | Nothing to do. The command is safe to re-run and changed nothing |
| Sign-in answers `403` with `syncr:origin-rejected` | The `Origin` header is missing or is not in `ALLOWED_ORIGINS` | Send the deployment's own origin, and check `ALLOWED_ORIGINS` names the tunnel hostname |
| Sign-in answers `401` with a password you are sure of | The stored email differs, or the session signing secret was rotated | Emails are compared lowercased and trimmed. A rotated secret invalidates sessions, not passwords, so re-check the email first |

There is no password-reset path in P0, and no command changes a password: re-running
`just bootstrap-user` with an existing email reports "nothing to do" and leaves the stored
hash alone. If the password is lost, delete the `users` and `tenants` rows for that
account and bootstrap again. With no plan data yet that costs nothing; once plan data
exists it would cost all of it, because every row is scoped to the tenant being deleted.
`rotate-secrets.md` owns the procedure that replaces this one when it lands.

## Tenancy: why row-level security is not enabled

Worth recording here, because this is the runbook that creates a tenant.

The schema is multi-tenant from its first migration: every table that holds a plan carries
a non-null `tenant_id`, and every repository over such a table takes its tenant as a
constructor argument, so an unscoped query is not something a caller can write by
forgetting an argument. Two tests enforce that: one compiles every statement a scoped
repository builds and asserts the predicate is present, and one records what Postgres
actually executed and asserts the same.

Postgres row-level security is **not** switched on, and that is a decision rather than an
omission. The threat RLS addresses is a bug in the application's own scoping leaking one
tenant's rows to another, and a P0 deployment has exactly one tenant to leak between.
Enabling it would add a policy per table, a role the application connects as, and a class
of failure where a correct query silently returns nothing.

Reconsider it when a second real tenant exists on one deployment. Adding it then needs no
re-indexing, because every composite index already leads with `tenant_id`, which is the
column an RLS policy filters on.
