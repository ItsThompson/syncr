# Google OAuth verification

## Trigger

Read this when any of the following happens:

- You are preparing to let anyone other than the owning account connect a Google calendar.
- Google emails about the app's verification status.
- A connect attempt shows a warning screen and you need to know whether that is expected.
- You are changing the requested scope set, which resets any verification already granted.

## Where things stand

| Property | Value |
|---|---|
| Google Cloud project | `syncr-504311` |
| Calendar API | enabled |
| Audience (user type) | External |
| Publishing status | In production |
| Branding verification | not verified. The app's name and logo are not shown on the consent screen |
| Data access verification | not verified. The app requests sensitive scopes |
| Restricted scopes requested | none |
| OAuth client | type "Web application", name `syncr web` |

A connect attempt therefore shows the "Google hasn't verified this app" screen. Clicking through it is the expected path: choose **Advanced**, then **Go to syncr (unsafe)**. Nothing is broken.

## The launch gate, named

There are two gates, and only one of them is a review. Confusing them wastes weeks.

**Gate 1: publishing status. Already cleared.** While publishing status was `Testing`, Google expired every authorization seven days after consent, and the refresh token with it. That behavior applies to any project with an External audience that requests more than name, email, and profile. For syncr it would kill the write target weekly, fire the `WriteTargetTokenExpiring` alert against a healthy system, and stop the plan reaching the phone. Publishing the app removed it. This gate was a button, not a review.

**Gate 2: OAuth verification. Not yet needed.** Verification is not mandatory for a personal-use app with fewer than 100 users. Users click through the unverified-app screen instead. Verification becomes necessary for exactly two reasons:

1. The app needs more than 100 users.
2. You want the app's name and logo on the consent screen, and the warning screen gone.

Neither applies to a single-user personal scheduler. So the gate to schedule is real but distant, and the thing that would have hurt weekly is already fixed.

## The 100-user cap

Requesting unapproved sensitive scopes caps the app at **100 new users over the project's entire lifetime**. The cap counts users, not authorizations, so reconnecting the same account does not consume the budget. It cannot be reset or raised without verification. At one user this is free, and it is the reason growing past personal use forces gate 2.

## What changes when verification completes

| Before | After |
|---|---|
| The unverified-app warning screen appears on every connect | The consent screen appears with no warning |
| The app's name and logo are hidden | The name and logo are shown, once branding is also verified |
| 100 new users, lifetime | The cap no longer applies to approved scopes |
| No annual obligation | Approved scopes are subject to Google's recertification cycle |

Verification does **not** change token lifetimes, scope behavior, or anything syncr's code does. No code path depends on verification status, so completing it requires no release.

## Requested scopes, verbatim

These three strings are what the OAuth client requests. They are recorded verbatim because changing the set invalidates verification, so a future reader needs the exact prior state.

```
https://www.googleapis.com/auth/calendar.calendarlist.readonly
https://www.googleapis.com/auth/calendar.events.readonly
https://www.googleapis.com/auth/calendar.events.owned
```

| Scope | Google's classification | What it serves |
|---|---|---|
| `calendar.calendarlist.readonly` | Non-sensitive | Listing the account's calendars during setup, and the per-source include or exclude choice |
| `calendar.events.readonly` | Sensitive | Reading events from anchor sources, including incremental reads by `syncToken` |
| `calendar.events.owned` | Sensitive | Reading and destructively reconciling events on the single write target |

No requested scope is **restricted**. That matters: restricted scopes trigger a third-party security assessment on top of verification, and an annual recertification with it. Adding a restricted scope later would change the gate from a form into an audit, so treat the restricted list as a boundary rather than a menu.

## Why this set, and where it is wider than syncr needs

The narrowest write scope Google offers is `calendar.app.created`, which reaches only calendars the app itself created. It is rejected because the write target is chosen by the user from calendars that already exist in the account, and a calendar created by hand is invisible to that scope. It also grants no anchor reads.

`calendar.events.owned.readonly` was rejected for anchor reads because a subscribed feed, such as a university timetable, is a calendar the account does not own.

Two of the three scopes are wider than syncr needs, for one shared reason: **Google has no per-calendar scope.**

- `calendar.events.readonly` can read every calendar in the account, not only the sources marked as included.
- `calendar.events.owned` can write to every calendar the account owns, not only the single write target.

The narrowing that matters is therefore enforced inside syncr and cannot be delegated to Google. `CalendarSource.included` gates which sources are read. The partial unique index on the write-target role gates writes to exactly one calendar. If either of those breaks, the OAuth grant will not stop the damage. That is the load-bearing consequence of accepting these two scopes, and it is why the write-target invariant is enforced in the database rather than in a service check.

## Credentials

| Item | Value |
|---|---|
| Client type | Web application |
| Environment variables | `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` |
| Secret file | `.env` at the repository root on a development machine, mode `0600`. Git ignores it |
| Rotation | Manual. Create a second client secret in the console, update the secret file, restart `api` and `worker`, confirm a connect still succeeds, then delete the old secret in the console. Two secrets can be valid at once, so there is no outage window |

Registered redirect URIs, all three exact strings:

```
https://syncr.app/api/v1/calendar-sources/google/callback
http://localhost:8000/api/v1/calendar-sources/google/callback
http://127.0.0.1:8000/api/v1/calendar-sources/google/callback
```

Google matches redirect URIs as exact strings, so `localhost` and `127.0.0.1` are two different registrations and both are present. `GOOGLE_OAUTH_REDIRECT_URI` selects which one a given process uses, and its value must appear verbatim in the list above.

`syncr.app` is HSTS-preloaded, so the deployed URI has no http form.

**The secret file must be the file Compose interpolates.** The `api` and `worker` services name the three variables explicitly in `docker-compose.yml` and interpolate them, rather than relying on `env_file` alone, so the topology shows which services hold Google credentials. Interpolation reads Compose's env file: the project-root `.env` by default, or whatever `--env-file` names. A secret file that Compose does not read as its env file resolves the variables to empty strings and the connect flow reports that Google is not configured. Empty is deliberately a valid state, so a machine with no Google credentials can still run the stack.

To seed a fresh machine, copy `.env.example` to `.env`, fill the two values from the OAuth client, and set mode `0600`. Delete any downloaded client JSON afterwards. Never paste either value into a terminal, a chat, or an issue.

## Calendars

Two secondary calendars exist in the owning account. Both are owned rather than subscribed, which is what `calendar.events.owned` reaches.

| Calendar | Role |
|---|---|
| `syncr` | The real write target for the deployed stack |
| `syncr (dev)` | The destructive-reconciliation target for development and tests |

Reconciliation removes every event in the horizon that syncr does not intend, including events it did not create. **Point it at `syncr (dev)` until the restore drill has passed.** A calendar holding real events is not a safe target, and neither is the account's primary calendar, which is read as an anchor source at most. A calendar acting as an anchor source can never be the write target: otherwise each solve would read the previous solve's output back as immovable external commitments.

## Two decisions recorded here rather than rediscovered

**The callback path is `/api/v1/calendar-sources/google/callback`.** The route catalog did not define one. It sits under the existing calendar-sources resource so the connect flow needs no new top-level namespace. Changing it means re-registering redirect URIs in the console, so it is fixed here.

**One Cloud project serves both development and production.** Google's OAuth policy suggests separate projects per tier. syncr deviates deliberately. The deployment is one host and one stack, and a second project would double the console surface, the client count, and the secret surface for a product with one user. What keeps destructive reconciliation away from real data is the development calendar, not a project boundary. Revisit this if a second person ever connects an account, because at that point the production project should not be the one used for experiments.

## Submitting for verification, when the time comes

1. Verify ownership of `syncr.app` in Google Search Console using the same account that owns the Cloud project. Verification requires every domain in the app's URIs to be a verified property.
2. Publish a privacy policy and terms of service at stable URLs on `syncr.app`.
3. Complete **Branding** in the Google Auth Platform console: app name, logo, home page, privacy policy, and terms of service. Branding must be verified before data access can be submitted.
4. Submit **Data Access** for verification. Justify each sensitive scope against a demonstrated feature, and record the justification alongside the scope table above.
5. Expect the review to ask for a demonstration video showing the consent flow and the feature each scope serves.

Adding or widening a scope after approval requires resubmission. Removing one does not.

## Verifying the setup works

```bash
# Both services receive a real client id, and nothing leaked into git.
docker compose config | grep -c 'GOOGLE_OAUTH_CLIENT_ID: .*apps.googleusercontent.com'   # 2
git check-ignore -v .env                                                                  # a .gitignore hit
git status --short .env                                                                   # no output
```

A connect attempt that reaches the Google consent screen and returns to the callback proves the client id, the secret, and the redirect URI all agree. A `redirect_uri_mismatch` error means `GOOGLE_OAUTH_REDIRECT_URI` differs from every registered string, usually by scheme, port, or a trailing slash.
