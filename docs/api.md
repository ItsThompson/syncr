# syncr API Reference

This page is the route catalog `docs/prd.md` section 1 deferred. It is a reading of the
committed OpenAPI document, `frontend/openapi.json`: the document is generated from the FastAPI
routes by `just contract`, which also regenerates the frontend's types from it, and a CI job
fails on a diff. The frontend never hand-writes a response type. Where this page and the
document disagree, the document governs; regenerate it and reread this page.

The CLI speaks this same API; how it obtains its credential is [authorization.md](authorization.md).
What each table stores is [database.md](database.md).

## Shape of the surface

- Resources live under `/api/v1`. Health (`/healthz`, `/readyz`), browser sign-in (`/auth`),
  the Authorization Server (`/oauth`), and discovery (`/.well-known`) sit outside the prefix,
  because they are how a caller becomes allowed to call the versioned routes rather than
  versioned resources themselves.
- Every `/api/v1` route requires a credential: the browser session cookie or a bearer access
  token. Which routes accept which is [authorization.md](authorization.md).
- A cross-tenant read answers `404`, never `403`, because a 403 confirms the row exists. A
  scope shortfall answers `403` and names what to re-authorize for.
- Mutations that record a verdict transition read an optional `X-Syncr-Session-Mode` header
  (`true`, `1`, `false`, `0`). It states whether the caller has the weekly session open, which
  feeds the early-catch product metric; absent means no session.
- `POST /api/v1/weeks/{iso_week}/approve` requires an `Idempotency-Key`. The solve request does
  not: it is idempotent per week by construction.
- `GET /api/v1/events` is the SSE stream. It accepts the session credential only and carries no
  plan documents, only operation, conflict, and notice events.

## Route catalog

### Discovery and health

| Method | Path | Summary |
|---|---|---|
| GET | `/.well-known/jwks.json` | The signing keys, current and previous |
| GET | `/.well-known/oauth-authorization-server` | Authorization Server metadata |
| GET | `/healthz` | Healthz |
| GET | `/readyz` | Readyz |

### Sign-in and consent

| Method | Path | Summary |
|---|---|---|
| POST | `/auth/login` | Establish a browser session |
| POST | `/auth/logout` | Revoke the current session |
| GET | `/auth/session` | The current principal |
| GET | `/oauth/authorize` | Ask the account holder to authorize a client |
| POST | `/oauth/authorize/decision` | Record the account holder's answer |
| POST | `/oauth/token` | Exchange a code, or refresh a token |
| POST | `/oauth/revoke` | Revoke a refresh token and its family |

### Areas, Projects, and preferences

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/areas` | Every Area, with the state of the pigment ramp |
| POST | `/api/v1/areas` | Declare an Area and deal it a pigment |
| GET | `/api/v1/areas/{area_id}` | One Area and the budget it declares |
| PATCH | `/api/v1/areas/{area_id}` | Change a name, floor, share, or pigment step |
| GET | `/api/v1/areas/{area_id}/preference` | An Area's preference, and what is in effect for it |
| PUT | `/api/v1/areas/{area_id}/preference` | Replace an Area's preference whole. The only shape taking a cap |
| DELETE | `/api/v1/areas/{area_id}/preference` | Remove an Area's preference. Nothing then biases its placement |
| GET | `/api/v1/projects` | Every Project, or the ones inside one Area |
| POST | `/api/v1/projects` | Declare a Project inside an Area |
| GET | `/api/v1/projects/{project_id}` | One Project |
| PATCH | `/api/v1/projects/{project_id}` | Change a name, deadline, or status |

Preferences follow one shape on every schedulable kind: a `GET` shows the override and what is
in effect, a `PUT` replaces the override whole, and a `DELETE` removes it so the Area's
preference applies again.

### Intents: tasks, habits, routines

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/tasks` | The backlog, with the counts its header states |
| POST | `/api/v1/tasks` | Capture a task. A title and an Area |
| GET | `/api/v1/tasks/{task_id}` | One task, with its remaining work |
| PATCH | `/api/v1/tasks/{task_id}` | Change a title, a deadline, or the physics |
| DELETE | `/api/v1/tasks/{task_id}` | Drop a task. The row survives, out of eligibility |
| POST | `/api/v1/tasks/{task_id}/complete` | Complete a task. Recorded time is left intact |
| GET | `/api/v1/habits` | Every habit, with its cursor and its debt |
| POST | `/api/v1/habits` | Declare a habit inside an Area |
| GET | `/api/v1/habits/{habit_id}` | One habit, with its cursor read-only and its provenance |
| PATCH | `/api/v1/habits/{habit_id}` | Change a cadence, duration, policy, source, or variants |
| DELETE | `/api/v1/habits/{habit_id}` | Remove a habit. Its recorded outcomes stay, because they are facts |
| GET | `/api/v1/routines` | Every routine, in the order the day runs |
| POST | `/api/v1/routines` | Declare a routine |
| GET | `/api/v1/routines/{routine_id}` | One routine |
| PATCH | `/api/v1/routines/{routine_id}` | Change a target time, a span, the floor, or the band |
| DELETE | `/api/v1/routines/{routine_id}` | Remove a routine, giving its span back to discretionary time |

Each of the three also carries the preference trio described above, on its own preference path:

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/tasks/{task_id}/preference` | A task's preference, and which one is in effect |
| PUT | `/api/v1/tasks/{task_id}/preference` | Replace a task's preference whole. It replaces its Area's |
| DELETE | `/api/v1/tasks/{task_id}/preference` | Remove a task's override, restoring its Area's preference |
| GET | `/api/v1/habits/{habit_id}/preference` | A habit's preference, and which one is in effect |
| PUT | `/api/v1/habits/{habit_id}/preference` | Replace a habit's preference whole. It replaces its Area's |
| DELETE | `/api/v1/habits/{habit_id}/preference` | Remove a habit's override, restoring its Area's preference |

### Day shapes and the week pattern

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/day-types` | Every day type |
| POST | `/api/v1/day-types` | Declare a day type |
| GET | `/api/v1/templates` | Every day shape, with its entry count |
| POST | `/api/v1/templates` | Declare a day shape |
| GET | `/api/v1/templates/{template_id}` | One day shape and its entries |
| PATCH | `/api/v1/templates/{template_id}` | Rename a day shape |
| DELETE | `/api/v1/templates/{template_id}` | Remove a day shape and its entries |
| POST | `/api/v1/templates/{template_id}/entries` | Add a concrete entry or a slot to a day shape |
| PATCH | `/api/v1/templates/{template_id}/entries/{entry_id}` | Move or resize one entry |
| DELETE | `/api/v1/templates/{template_id}/entries/{entry_id}` | Remove one entry from a day shape |
| GET | `/api/v1/week-pattern` | Which day type each weekday uses |
| PUT | `/api/v1/week-pattern` | Replace the whole mapping. All seven weekdays required |

### Anchors and their types

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/anchor-types` | Every anchor type, in evaluation order |
| POST | `/api/v1/anchor-types` | Declare an anchor type at the end of the order |
| PUT | `/api/v1/anchor-types/order` | Reorder the rules. Re-evaluates existing commitments |
| GET | `/api/v1/anchor-types/{anchor_type_id}` | One anchor type and the shadow it declares |
| PATCH | `/api/v1/anchor-types/{anchor_type_id}` | Change a match rule or a shadow member |
| DELETE | `/api/v1/anchor-types/{anchor_type_id}` | Remove an anchor type. Its commitments return to rule matching |
| GET | `/api/v1/anchors` | Commitments in a span. Read-only |
| GET | `/api/v1/anchors/{anchor_id}` | One commitment, with its source named |
| PUT | `/api/v1/anchors/{anchor_id}/type` | Retype a commitment. Persists on the series |

### Calendar sources and Google connect

An ICS feed needs no OAuth. A Google account connects through the three dedicated `google`
routes in this group beside the generic source routes; the flow itself, its state parameter,
and token refresh are covered in [authorization.md](authorization.md).

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/calendar-sources` | Every calendar source, with its sync state |
| POST | `/api/v1/calendar-sources` | Add an anchor source. No OAuth for an ICS feed |
| GET | `/api/v1/calendar-sources/google/callback` | Where Google returns from consent. Redirects to Settings with the outcome |
| POST | `/api/v1/calendar-sources/google/connect` | Start a Google connect. Names the scopes and what is read |
| GET | `/api/v1/calendar-sources/google/connection` | Whether Google is connected, and every notice it raises |
| DELETE | `/api/v1/calendar-sources/{source_id}` | Remove a source and the anchors it contributed |
| GET | `/api/v1/calendar-sources/{source_id}` | One source and its sync state |
| PATCH | `/api/v1/calendar-sources/{source_id}` | Include or exclude a source, or rename it |
| PATCH | `/api/v1/calendar-sources/{source_id}/horizon` | Set the projection horizon. Write-target only |
| GET | `/api/v1/calendar-sources/{source_id}/remote-calendars` | The account's calendars, for selection during setup. Google only |
| PUT | `/api/v1/calendar-sources/{source_id}/role` | Assign the write-target role. 409 if one exists |
| POST | `/api/v1/calendar-sources/{source_id}/sync` | Force a sync. Returns an Operation |

### Weeks, solving, and assent

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/weeks/{iso_week}` | The composed week view. Writes nothing |
| POST | `/api/v1/weeks/{iso_week}/solve` | Request a solve of this week. Idempotent per week, and needs no key |
| GET | `/api/v1/weeks/{iso_week}/verdict` | The verdict alone, for a cheap refresh. Writes nothing |
| GET | `/api/v1/weeks/{iso_week}/proposal` | The pending proposal, or 404 when the slot is empty |
| POST | `/api/v1/weeks/{iso_week}/approve` | Approve the pending proposal. Needs an Idempotency-Key |
| POST | `/api/v1/weeks/{iso_week}/pins` | Pin a block where the user put it. Returns the pin, the verdict, and the operation |
| DELETE | `/api/v1/weeks/{iso_week}/pins/{pin_id}` | Release one pin. Bumps the week's input version and re-solves |
| POST | `/api/v1/weeks/{iso_week}/reject-block` | Reject one proposed move by pinning the block at its existing placement |
| POST | `/api/v1/weeks/{iso_week}/tradeoffs` | Solve this week against one tradeoff. Persists nothing; returns an operation |
| GET | `/api/v1/weeks/{iso_week}/adjustments` | The concessions this week has absorbed |
| DELETE | `/api/v1/weeks/{iso_week}/adjustments/{adjustment_id}` | Revoke one concession. Bumps the week's input version and re-solves |
| GET | `/api/v1/weeks/{iso_week}/revisions` | Revision history for the week. Read-only |

The week view is the Week screen's whole read in one request: live blocks, pins, conflicts,
adjustments, readings, the pending proposal, and the non-terminal operation if one is in
flight. When the tenant cannot plan yet, it answers instead with readiness statements that say
which inputs are missing, so the grid can say why it is empty rather than render nothing. Every
placed block carries an `objectiveDelta`, the objective contribution of the placement it
superseded or absorbed, which is what pins, proposals, and conflict answers hand back to the
caller.

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/conflicts` | The conflicts this account holds. Writes nothing |
| POST | `/api/v1/conflicts/{conflict_id}/resolve` | Answer one conflict, and do what that answer names |
| GET | `/api/v1/operations` | List tracked operations, most recently scheduled first |
| GET | `/api/v1/operations/{operation_id}` | Read one operation's current status |
| POST | `/api/v1/promotions/{promotion_id}/accept` | Absorb a repeated pin into the day shape |
| POST | `/api/v1/promotions/{promotion_id}/decline` | Decline it, and do not raise it again for a while |
| GET | `/api/v1/events` | The event stream. Session credential only, and it carries no plan documents |

### Days, outcomes, budget, and reviews

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/days/{date}` | The Today ledger for one date |
| POST | `/api/v1/days/{date}/confirm` | Confirm one day, converting presumption into record |
| POST | `/api/v1/days/confirm-range` | Confirm several past days in one call |
| PUT | `/api/v1/blocks/{block_id}/outcome` | Record what happened to one block |
| GET | `/api/v1/budget` | Discretionary time, per-Area target and actual, and the two residuals |
| GET | `/api/v1/reviews/week/{iso_week}` | The weekly session's payload. Writes nothing |
| GET | `/api/v1/reviews/budget` | Composition, trend, deviation, and the proposed percentages |
| POST | `/api/v1/reviews/budget/apply` | Apply proposed percentages, wholly or adjusted |

### Off-plan spans, settings, learning

| Method | Path | Summary |
|---|---|---|
| GET | `/api/v1/off-plan` | Every declared off-plan period |
| POST | `/api/v1/off-plan` | Declare a span off-plan. 409 on an overlap |
| GET | `/api/v1/off-plan/{period_id}` | One off-plan period |
| PATCH | `/api/v1/off-plan/{period_id}` | Move a bound, rename a span, or change keepFrame |
| DELETE | `/api/v1/off-plan/{period_id}` | Remove a period, so its span is on plan again |
| GET | `/api/v1/settings` | Grid geometry, home zone, review cadence, and the active zone |
| PATCH | `/api/v1/settings` | Change visible hours, day bounds, home zone, or review cadence |
| GET | `/api/v1/settings/travel-overrides` | Declared ranges in another zone |
| POST | `/api/v1/settings/travel-overrides` | Declare a range in another zone |
| DELETE | `/api/v1/settings/travel-overrides/{override_id}` | Remove a declared range |
| GET | `/api/v1/learned` | What has been learned, and what is still collecting |
| GET | `/api/v1/weight-sets` | Every version, with origin and active flag |
| POST | `/api/v1/weight-sets/{version}/activate` | Activate a version, or revert to an earlier one |
