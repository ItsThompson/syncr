# Google write-target token expired

## Trigger

Either of these means the write target's OAuth token can no longer be refreshed:

- The in-product banner appears, in oxide, on every screen, with a panel on Settings.
- `GET /api/v1/google/connection` carries a notice whose `id` starts `google.write-target-expired`.

The `WriteTargetTokenExpiring` alert is defined against `syncr_write_target_token_age_seconds`, and **that metric is now exported**: the worker's state-gauge duty sets it once a minute from `google_credentials.refresh_failing_since`, which is the age of the CONDITION rather than of a credential. It reads zero while refreshes work and grows from the instant one starts failing, so the rule is `max(...) > 0 for 15m` and needs no invented threshold. Nothing about this failure is silent in the product either: the banner is raised from the credential's own record and is the notice this runbook is written around.

## Why this is the loudest failure in the product

Reading anchors keeps working. Solving keeps working. The plan keeps updating. Only the projection stops, so the calendar on the phone silently freezes at the last successful write while syncr itself looks healthy. The write target exists to get the plan onto the phone, so this failure removes the product's entire delivery mechanism while presenting no symptom in syncr. That is why the notice is a banner rather than a panel, and why the alert is critical rather than a warning.

## Surviving capability, which the notice must state

- **ICS anchor sources still sync**, so a timetable published as a feed is still read.
- **A Google-provider anchor source does NOT.** One credential per tenant serves both the anchor reads
  and the write target, so a revoked grant stops both, and `SourceStale` follows about a day later on
  every Google source. That pair is one repair, and it is a named Alertmanager inhibit rule for that
  reason: `WriteTargetTokenExpiring` suppresses `SourceStale`.
- The plan is still solved and still correct in syncr, against whatever it last read.
- Writes to the calendar are failing, so the phone is stale from the timestamp in the banner.

## If this alert is firing and the token age reads ZERO

**Check this before working through the procedure below, because in this case nothing is wrong with the
token and the first three steps will all say so.**

The alert has a second cause:

```
or increase(syncr_observability_tenant_failures_total[15m]) > 0
```

The token age gauge is set by the worker's state duty, whose per-tenant fault is **contained and
counted rather than raised**. So a duty that raises on every tick leaves the gauge at its last value,
and its last value is 0, which is the healthy reading. Without that disjunct this alert would stay
quiet while writes to the calendar failed. Measured: with the per-tenant read raising, the gauge holds
**0.0 with its series present** while the counter increments.

Tell the two causes apart:

```
syncr_write_target_token_age_seconds              # > 0 means a real token problem: continue below
increase(syncr_observability_tenant_failures_total[15m])   # > 0 means the state duty is raising
```

If the counter is what fired, read the worker log for the `observability.state.tenant_failed` event.
**The likely cause is a mis-rotated `GOOGLE_TOKEN_ENCRYPTION_KEY`**: the credential read raises on
every tick, no gauge moves, `refresh_failing_since` stays NULL, and every product surface looks
healthy. `rotate-oauth-signing-key.md` covers the key's own procedure.

## The reconnect path

Reconnecting is a user action, not an operator action. The banner and the Settings panel each offer a single **Reconnect** action. It restarts the Google authorization flow for the same account, issues a fresh refresh token, and replaces the stored one. Nothing else needs to change: the calendar selection, the write-target role, and the horizon all survive a reconnect, because the token is the only thing that expired.

After reconnecting, the next projection run brings the write target back into agreement with the live plan. Reconciliation is destructive over the horizon, so any event the user hand-created on the target while writes were failing is removed and counted as a foreign deletion.

## Rule out first

Check the app's publishing status in the Google Auth Platform console before investigating anything else. A project with an External audience and a publishing status of `Testing` expires every authorization seven days after consent, and the refresh token with it. If the status has reverted to `Testing`, the token did not fail: Google revoked it on schedule, and reconnecting weekly is the only alternative to publishing the app. See `google-oauth-verification.md`.

## Why a refresh token stops working

Google names the causes. Work down this list before assuming a bug, because three of these are scheduled behavior rather than failure, and one of them leaves no trace at the moment it happens.

| Cause | How it presents | Reachable here |
|---|---|---|
| Publishing status is `Testing` | Every grant dies seven days after consent, on schedule | Yes. Check it first, per above |
| The token went unused for six months | A refresh that worked before fails after a long gap with no other change | Yes, after a paused deployment or a write target that sat unconfigured |
| The account holds more than 100 live refresh tokens for this client id | **No error at the time.** Minting token 101 silently invalidates the oldest, which then fails on *its* next refresh, long after the reconnect that displaced it | Yes, and exercising the reconnect path repeatedly is what causes it |
| The user revoked the app's access | Refresh fails permanently. Only reconnecting recovers it | Yes |
| The user granted time-limited access at consent | Refresh fails when the granted period ends | Yes |
| The user changed their password | Invalidates only refresh tokens carrying Gmail scopes | **No.** syncr requests no Gmail scope, so a password change is not the cause |
| An administrator restricted a requested service | `admin_policy_enforced` | **No**, while the owning account is personal rather than Workspace |

The last two rows exist to be ruled out fast. Both are common explanations for this symptom in general and neither can apply to syncr as configured.

The third row is the one that misleads. It decouples cause from symptom in time: the reconnect that crossed the limit succeeds and looks healthy, and the failure appears later against a different grant. A token that fails with no recent change to publishing status, no revocation, and recent activity is the signature. `google-oauth-verification.md` records the limit alongside the user cap, which is a different hundred.

## Confirm that refresh is the failing step

Work in this order. Each step rules out one thing, and the first two are reads that cost nothing.

**1. Read the connection.** `GET /api/v1/google/connection` returns the notices this integration raises. Two conditions raise notices and they are different failures:

| Notice id starts | Condition | Section to read |
|---|---|---|
| `google.write-target-expired` | The stored authorization can no longer be refreshed | This runbook |
| `calendar.projection-stopped` | The projection stopped for some other reason | `## When it is not the token` |

Both can be raised at once. The expiry is the one to act on first, because it is also a cause of the other.

**2. Read the write target.** `GET /api/v1/calendar-sources` returns every source; the one holding `role: "write-target"` also carries a `writeTarget` object. Its `syncState` is the projection's own record:

| Field | What it says |
|---|---|
| `lastSuccessAt` | When the plan last reached the calendar. This is how old what the phone shows is |
| `lastAttemptAt` | When syncr last tried. Recent, with an older `lastSuccessAt`, is a target that is failing |
| `lastError` | Why the last attempt stopped, in the words the banner renders |
| `attempts` | How many provider calls the last attempt made |

A target whose `lastAttemptAt` is null has never been projected to at all, which is a setup state rather than a failure.

**3. Read the operations.** `GET /api/v1/operations?kind=projection` returns the queue's own history, newest first. Each row carries `status`, `attempt`, and an `error` with a `code`. Two codes exist and they mean different things:

| `error.code` | Meaning | Fix |
|---|---|---|
| `projection_refused` | syncr will not write at all, and nothing was sent. Not retried, because retrying cannot clear it | An operator arms the deployment, or a user designates a calendar syncr can write to. See below |
| `projection_failed` | A write was attempted and did not complete | Depends on `error.message`, which states the provider's own reason |

**4. Read the logs.** Every pass emits one line, and which line it is answers what happened:

| Event | Meaning |
|---|---|
| `calendars.projection.completed` | The target matches the plan. Carries the counts per action |
| `calendars.projection.failed` | It did not. Carries `error_code` and the counts that DID land |
| `calendars.projection.skipped` | No calendar is designated as the write target. Nothing was attempted |
| `calendars.projection.tenant_failed` | The pass raised outside a stated failure. A defect, with a traceback |

**A `tenant_failed` line is the one case with no banner.** Every stated failure records itself on the write target, so the user sees it; a pass that raised outside them recorded nothing, and the operations it claimed sit `running` until the reaper returns them. Two shapes reach it: a fault in syncr, and two events syncr intends sharing one key (`ProjectionKeysCollide`), which is a fault in the plan's collection rather than at the provider. Read the traceback, and read `syncr_projection_tenant_failures_total`, which counts them.

No log line carries a token, a calendar title, or an event title. That is enforced by the logger's own redaction and asserted by the suite, so a line will not tell you which event failed to write, by design.

## Distinguish the three ways refreshing stops working

Only ONE of these sets the credential's failure record, and that asymmetry is the diagnosis.

| What happened | What syncr records | How to tell |
|---|---|---|
| The grant is gone: revoked, expired, replaced | `refresh_failing_since` and `last_refresh_error` are set, and the expiry banner is raised | The banner is present. Google answered `invalid_grant` |
| Google could not be asked: a network fault, a 5xx at the token endpoint, a timeout | **Nothing.** The credential is untouched | No expiry banner, and the projection failure names a status or a transport error rather than an authorization |
| The token is fine and the CALENDAR refused the write | Nothing on the credential; `lastError` on the write target | No expiry banner. `error.message` says the account may no longer be allowed to write |

That asymmetry is deliberate: treating an unreachable token endpoint as a dead grant would raise the loudest notice in the product against a healthy credential and teach the reader to ignore it.

Read the failure record directly when the api is not available:

```sql
SELECT tenant_id, connected_at, last_refresh_at, refresh_failing_since, last_refresh_error
FROM google_credentials;
```

The two failure columns move together, enforced by a check constraint, so one set and the other null is a corrupt row rather than a state to interpret.

## Tell a displaced token from a revoked one

Both fail permanently, both answer `invalid_grant`, and neither announces itself at the moment it happens. The distinguishing evidence is syncr's own record of when each grant was issued.

| Evidence | Revoked by the user | Displaced by the 100-token limit |
|---|---|---|
| `connected_at` | Any age | Old. The grant that displaced it was minted later |
| Reconnects since | None needed to explain it | Several. Each reconnect mints a token and the oldest is discarded silently |
| Google account activity | The app appears removed from the account's third-party access list | The app is still listed and still authorized |

Each connect REPLACES the row, deleting the previous one, so `connected_at` is the instant of the most recent connect and not a history. If you need the history, it is in the log: `google_account.connected` is emitted once per successful connect.

The practical answer is the same either way, which is why this is the last thing to establish rather than the first: reconnect. What it changes is whether to expect the failure again, and repeatedly exercising the reconnect path is what causes the displacement in the first place.

## Prove the write target is current after reconnecting

Reconnecting stores a fresh grant; it does not project. The next projection does that, and a projection is enqueued only when the live plan changes, so **nothing may happen for hours** on a quiet week. Force it rather than waiting:

1. Confirm the grant took. `GET /api/v1/google/connection` shows `connected: true`, a fresh `connectedAt`, and **no** notice whose id starts `google.write-target-expired`.
2. Make the live plan change, which is what enqueues a projection. Any mutation that appends a revision does; the plan horizon maintainer also plans any horizon week that has none, on its own fifteen-minute tick.
3. Watch for `calendars.projection.completed` in the worker's log. It carries `inserted_count`, `patched_count`, `deleted_count` and `foreign_deleted_count`.
4. Read the write target again. `syncState.lastSuccessAt` has moved and `syncState.lastError` is null.
5. Read the calendar on the phone. The first projection after an outage is the one likely to show a non-zero `foreign_deleted_count`: reconciliation is destructive over the horizon, so anything the user created by hand there while writes were failing has now been removed.

A projection that succeeds and writes nothing is the healthy steady state, not a failure to converge: the reconciliation writes only the difference, so a target that already matches the plan produces no provider call at all.

## When it is not the token

The projection stops for reasons that have nothing to do with the authorization, and each states itself in `error.code` and in `syncState.lastError`.

| Cause | What the message says | Fix |
|---|---|---|
| Writing is switched off in this deployment | "writing is switched off", and it names `GOOGLE_PROJECTION_WRITES` | An operator sets `GOOGLE_PROJECTION_WRITES=true` and restarts the worker. **Off is the shipped default**: the destructive write has met the real Google API only from the marked live suite against a development calendar, never from an armed deployment over a horizon of real plan blocks |
| This deployment has no Google OAuth client | "no Google OAuth client" | Set the three `GOOGLE_OAUTH_*` values and restart |
| The designated write target is an ICS feed | "a feed is published by somebody else" | Designate a Google calendar. A feed cannot be written to at all, and this is a **refusal**: it is not retried, because retrying cannot change a source's provider |
| The reconciliation ran out of time | "stopped after 90s without finishing" | Nothing, immediately. It states the counts that landed and the next pass converges. A first projection of a full horizon is the likely one; if it recurs, the horizon is larger than the budget and `horizon_days` is the lever |
| Google rate limited the write | "rate limiting" | Nothing. It retries, and the next reconciliation converges |
| Google answered a 5xx, or the connection dropped | "Whether it was applied is unknown, so it was not retried" | Nothing. The next reconciliation recomputes the diff from a fresh read |

The last three are worth understanding rather than acting on. A write is retried in place only when Google is known to have rejected it; anything ambiguous ends the reconciliation, because retrying a write that may have been applied is what would put two copies of one block on the phone. A reconciliation that ran out of time is the same shape: part of the plan reached the calendar and part did not, and the pass says which.

## Still to be written

Nothing. The five open items this runbook carried are answered above.
