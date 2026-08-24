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

**Google labels this state "strongly discouraged."** Its publishing-status matrix says of a published, external, unverified app: "Any Google user can access. Strongly discouraged." The label is recorded here rather than left out, because a runbook whose job is naming gates honestly should not quietly omit the vendor's own warning on the state it recommends. The judgment stands at one user: the alternative, `Testing`, expires the write target's token every seven days, which is a certain weekly failure against a warning about a risk that does not apply while the only user is the developer. Anyone weighing a second user should reopen this trade rather than inherit it.

## The launch gate, named

There are two gates, and only one of them is a review. Confusing them wastes weeks.

**Gate 1: publishing status. Already cleared.** While publishing status was `Testing`, Google expired every authorization seven days after consent, and the refresh token with it. That behavior applies to any project with an External audience that requests more than name, email, and profile. For syncr it would kill the write target weekly, fire the `WriteTargetTokenExpiring` alert against a healthy system, and stop the plan reaching the phone. Publishing the app removed it. This gate was a button, not a review.

**Gate 2: OAuth verification. Not yet needed.** Verification is not mandatory for a personal-use app with fewer than 100 users. Users click through the unverified-app screen instead. Verification becomes necessary for exactly two reasons:

1. The app needs more than 100 users.
2. You want the app's name and logo on the consent screen, and the warning screen gone.

Neither applies to a single-user personal scheduler. So the gate to schedule is real but distant, and the thing that would have hurt weekly is already fixed.

## Two different hundreds

Both limits are 100. They count different things, and only one of them is unaffected by reconnecting.

**The OAuth user cap: 100 users, per project, over the project's lifetime.** It applies because the app requests unapproved sensitive scopes. It counts *users*, so reconnecting the same account does not consume it. It cannot be reset or raised without verification. At one user it costs nothing, and it is the reason growing past personal use forces gate 2. Google words this cap as "100 new users" on one page and "a hard cap of 100 total users" on another; the ceiling is 100 either way.

**The refresh-token limit: 100 live refresh tokens, per Google account, per OAuth client id.** Reconnecting **does** consume this one, because each authorization mints a new refresh token. On reaching the limit, creating the next token **silently invalidates the oldest, with no error and no notice**. A separate, larger limit applies to one account across all clients.

So reconnecting is free against the user cap and not free against the token limit. Exercising the reconnect path repeatedly, which is what developing and testing that path looks like, moves toward the token limit rather than away from it. At a hundred reconnects the symptom is not a refusal: it is an older grant dying quietly somewhere else.

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

## What ends a refresh token

The client id and secret are long-lived. The per-user refresh token is not, and it dies for reasons that have nothing to do with the credentials above. Recorded here as the durable reference; `google-token-expired.md` owns diagnosing which one fired.

| Cause | Bound |
|---|---|
| Publishing status is `Testing` | Seven days from consent. Cleared by gate 1 above |
| The token goes unused | Six months |
| The account exceeds 100 live refresh tokens for one client id | Not a refusal: the oldest is invalidated silently. See *Two different hundreds* above |
| The user revokes access, or granted time-limited access at consent | Immediate, or at the end of the granted period |

Two causes Google lists do **not** apply to syncr, and are worth knowing so they are not chased: a password change invalidates only refresh tokens carrying Gmail scopes, and syncr requests none; and `admin_policy_enforced` needs a Workspace administrator, while the owning account is personal.

## Calendars

Two secondary calendars exist in the owning account. Both are owned rather than subscribed, which is what `calendar.events.owned` reaches.

| Calendar | Role |
|---|---|
| `syncr` | The real write target for the deployed stack |
| `syncr (dev)` | The destructive-reconciliation target for development and tests |

Reconciliation removes every event in the horizon that syncr does not intend, including events it did not create. **Point it at `syncr (dev)` until the restore drill has passed.** A calendar holding real events is not a safe target, and neither is the account's primary calendar, which is read as an anchor source at most. A calendar acting as an anchor source can never be the write target: otherwise each solve would read the previous solve's output back as immovable external commitments.

## Running the live Google suite

`packages/syncr-api/tests/test_google_live.py` is the only suite that talks to Google. Everything else about the integration is proven against a fake, which is the right default; what a fake cannot prove is that syncr's reading of Google's contract matches Google's. The suite is excluded from every default run by a marker rather than a skip, so it runs only when somebody asks for it:

```bash
cd packages/syncr-api && uv run pytest -m google_live -s
```

`-s` is what shows the measured durations. Without it a passing run prints no figure.

### The four values it reads

All four come from the process environment, and nothing loads a dotenv for this suite, so exporting them is part of running it. An absent value skips every test and names what is missing.

| Variable | Where it comes from |
|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | the OAuth client in *Credentials* above. Shipped empty in `.env.example`; the real value lives in the repository-root `.env`, which is the layer that supplies it |
| `GOOGLE_OAUTH_CLIENT_SECRET` | the same |
| `GOOGLE_OAUTH_REDIRECT_URI` | `.env.example` ships the default, `/api/v1/calendar-sources/google/callback` on `localhost:8000`, and the root `.env` may override it. Whatever the layer, the value must appear verbatim in the console's registered list |
| `SYNCR_GOOGLE_LIVE_REFRESH_TOKEN` | the procedure below. Shipped nowhere, never committed, never a fixture, never printed |

Read the three out of the secret file rather than sourcing it: an env file is data, and `.` executes
it. Each `export` below also states the name, which is what lets a reader of this file see the whole
set without running anything.

```bash
cd packages/syncr-api
export GOOGLE_OAUTH_CLIENT_ID="$(grep -m1 '^GOOGLE_OAUTH_CLIENT_ID=' ../../.env | cut -d= -f2-)"
export GOOGLE_OAUTH_CLIENT_SECRET="$(grep -m1 '^GOOGLE_OAUTH_CLIENT_SECRET=' ../../.env | cut -d= -f2-)"
export GOOGLE_OAUTH_REDIRECT_URI="$(grep -m1 '^GOOGLE_OAUTH_REDIRECT_URI=' ../../.env | cut -d= -f2-)"
export SYNCR_GOOGLE_LIVE_REFRESH_TOKEN=     # then paste the value from step 7
```

**`GOOGLE_OAUTH_REDIRECT_URI` is not `APP_BASE_URL`, and confusing them wastes a consent.** The redirect URI is the string Google matches character for character and sends the browser back to. `APP_BASE_URL` is where the callback sends the *user* afterwards, the browser application's own origin, and it is read only to build that final redirect. `.env.example` ships them as different origins for that reason. No compose file names `APP_BASE_URL`; it reaches a container through `env_file`, and an empty or whitespace value falls back to `PUBLIC_BASE_URL`.

The token has to be minted against that same client id, by the account that owns `syncr (dev)`, carrying all three scopes. A grant narrower than the three does not skip: it fails, on whichever call it cannot make.

### Two costs to weigh before consenting

**Consenting mints a refresh token, and one account holds at most 100 live ones per client id.** At the limit Google invalidates the oldest silently, with no error and no notice anywhere. So consent once and keep the token rather than repeating this procedure. *Two different hundreds* above has the detail.

**A refresh token that goes unused for six months dies.** Running this suite occasionally is what keeps it alive.

### Obtaining the refresh token

`access_type=offline` is what makes Google issue a refresh token at all, and `prompt=consent` is what makes it issue a new one for an account that has already granted these scopes. Without both, the exchange answers with an access token and nothing to store.

1. Sign the browser in as the account that owns `syncr` and `syncr (dev)`. Any other account produces a token the suite will not use, because it finds its target calendar by name.
2. Open the authorization URL: `https://accounts.google.com/o/oauth2/v2/auth`, carrying `response_type=code`, `access_type=offline`, `prompt=consent`, the `client_id` from `.env`, the `redirect_uri` from `GOOGLE_OAUTH_REDIRECT_URI` verbatim, and `scope` set to the three strings in *Requested scopes, verbatim* above, separated by spaces.
3. The consent screen says "Google hasn't verified this app". That is the expected path, for the reason *Where things stand* gives: choose **Advanced**, then **Go to syncr (unsafe)**.
4. Grant all three scopes. Declining any one produces a grant the suite cannot use.
5. Google sends the browser to the redirect URI carrying `?code=...`. Nothing is listening on that port unless the dev stack is running, so the browser shows a connection error; the code is in the address bar either way. Copy it. It is single-use and expires in minutes.
6. Exchange the code at `https://oauth2.googleapis.com/token` with `grant_type=authorization_code` and the same client id, client secret and redirect URI. The answer carries `refresh_token`.
7. Export it as `SYNCR_GOOGLE_LIVE_REFRESH_TOKEN`. Never paste it into a chat, an issue, or a shell that records history.

The alternative is to complete syncr's own connect flow against a development deployment, which stores the token encrypted in `google_credentials.encrypted_refresh_token`; recovering the plaintext then means decrypting that column with `GOOGLE_TOKEN_ENCRYPTION_KEY`. The exchange above stores it nowhere.

### What the suite does to the account, in the order it does it

**It reads wide before it writes anything.** One test reads events over the next 14 days from **every** calendar in the account, the primary included, because its claim is about every timestamp Google sends rather than about one calendar chosen to be convenient. It reports identifiers and refusal reasons and never a title. It writes nothing.

**Every write lands on `syncr (dev)`.** The suite finds that calendar by name and refuses to run if the account does not hold it, rather than falling back to another one.

**One test is destructive over its window.** The reconciliation removes every event inside its window that syncr did not put there, including one created by hand. That window is 2 hours long, starts at the top of the current hour, and sits 2 days ahead of the moment the suite runs. The suite reads the window first and refuses if anything occupies it, naming the calendar, both bounds and the identifiers, so clearing it is the repair.

**The three write probes are not destructive.** Each sends one insert and then a patch or a delete against the identifier the provider gave that insert, and removes what it made. They take one day each, three, four and five days ahead.

So before running this, **the development calendar must hold nothing between 2 and 5 days from now.** A failed run can leave one event behind, titled `syncr live suite · safe to delete`; deleting it by hand is safe, and is sometimes what the next run needs.

## The connect flow's state, and why there is no PKCE here

Google sends the browser back to the callback URL with the code in the address bar. Anyone can
build such a URL: a link in an email, or a page that silently redirects to the callback carrying a
code the attacker obtained. Without a binding to the flow that started, the callback would connect
whichever Google account the attacker chose to whoever is signed in at syncr, and report success.
That threat, login CSRF by code injection, is what the `state` parameter answers.

The state answers that threat and nothing else. It says nothing about who sees the code while it
travels from Google's consent screen to syncr's callback; that is the threat PKCE addresses. One
parameter cannot carry both, so the judgment below rests on four properties of the state instead,
each pinned by a test against `google_account/state.py` that goes red if an edit weakens it:

| Property | What it means | What it refuses |
|---|---|---|
| Signed | An HMAC over the whole value under a key derived from the deployment signing secret for this one purpose | A state nobody here issued |
| Tenant-bound | Carries the tenant it was issued for | A state whose tenant was edited after issue |
| Short-lived | Refused once it is more than **15 minutes** old | A flow somebody abandoned days ago |
| Session-compared | The callback compares the verified tenant against the signed-in session's tenant | A code obtained in one account connecting whoever is signed in now |

**Why there is no PKCE in this flow.** PKCE binds an authorization code to a secret held only by
the party that started the flow, which matters most for public clients that have no other secret.
syncr is a confidential client here: the code is exchanged at Google's token endpoint together
with `GOOGLE_OAUTH_CLIENT_SECRET`, which Google verifies server to server. A code read off the
browser cannot be redeemed without that secret. The CLI against syncr's own authorization server
is a different client with no such secret, and that server keeps PKCE for it.

**What would reopen the question:**

- The exchange stops presenting the client secret, making this an effectively public client.
- Google deprecates the confidential-client grant or mandates PKCE for web applications.
- A second front end appears whose origin the deployment does not control end to end over HTTPS.

Adding PKCE then needs the verifier to survive the round trip, carried inside the state or stored
server-side against a flow identifier. That is design work, not a query parameter.

## Two decisions recorded here rather than rediscovered

**The callback path is `/api/v1/calendar-sources/google/callback`.** The route catalog did not define one. It sits under the existing calendar-sources resource so the connect flow needs no new top-level namespace. Changing it means re-registering redirect URIs in the console, so it is fixed here. Note for whoever adds the route: this puts a literal `google` where the sibling calendar-source routes put `{id}`. Nothing collides, because no sibling has the shape `/calendar-sources/{id}/callback`, but a router that greedily matches `{id}` two segments deep would capture it.

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
