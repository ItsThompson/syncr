# syncr Authorization

This page is the authorization model `docs/prd.md` section 1 deferred. It covers who a request
is for, what it may do, and how each kind of client proves both: the browser session, the
CLI's OAuth tokens against syncr's own Authorization Server, and the Google connect flow that
lets syncr read and write the user's calendars.

## The principal

The principal is who the request is for and what it may do: one value carrying the tenant, the
user, and the scopes. It is resolved once at the HTTP edge from whichever credential the
request presented, then passed explicitly into every service method as their first argument.
There is no ambient principal to read from a context variable, because an ambient read is how a
new caller silently skips authorization.

Authorization is two checks, called together by every service method:

- **Tenant.** A mismatch raises `404`, never `403`. A 403 on someone else's row confirms the
  row exists; a 404 says only that the caller has nothing by that identifier. Both denials are
  logged, because the wire deliberately says little.
- **Scope.** A shortfall raises `403`, because a scope answer discloses nothing and being told
  the credential is too narrow is what lets a client re-authorize instead of guessing.

## Scopes

Three, deliberately coarse:

| Scope | Authority |
|---|---|
| `plan:read` | Read the plan and everything it is built from |
| `plan:write` | Change the plan |
| `admin` | Administrative operations |

A browser session carries all of them, because the user is acting directly and there is no
third party to withhold authority from. A bearer token carries only what its grant was issued
for, which is what makes a stolen CLI token less than a stolen password.

## The browser credential

Sign-in is `POST /auth/login` with email and password. Rejections are indistinguishable on the
wire: the answer is always "sign in", never whether the email exists or which part was wrong.
That distinction lives in the log, where it is an operator's question.

A successful sign-in mints a session token that appears once, in the cookie, and is stored only
as a digest. The cookie is `syncr_session`, with attributes that are not parameters:

- `HttpOnly`, so no script can reach the token;
- `Secure`, so it never rides a plaintext connection;
- `SameSite=Lax`, so cross-site unsafe requests carry nothing; `Strict` would also withhold it
  from the sign-in redirect back to the page the user asked for;
- an explicit `max_age` of the session's absolute lifetime, so quitting the browser does not
  sign the user out.

The server holds the real clock. Each session has a 14-day idle window that slides on use (the
rewrite throttled to at most one per minute) and a hard 90-day cap no amount of use extends. A
cookie left past either just draws a 401, and the app sends the user to sign in.

## Client credentials: the Authorization Server

syncr runs its own OAuth Authorization Server so the CLI (and the user's AI agent through it)
can hold less than the browser does.

Discovery is published at `/.well-known/oauth-authorization-server` and signing keys at
`/.well-known/jwks.json`. The flow is authorization code with PKCE, S256 only (`plain` is
refused), because the CLI is a public client with no secret:

1. The CLI generates a `code_verifier`, derives its S256 challenge, starts a loopback listener
   on an ephemeral port bound to `127.0.0.1`, and opens the browser at `/oauth/authorize`.
2. The consent screen names the scopes being requested. Only a signed-in browser session can
   approve it; a bearer token cannot mint itself a new grant, widen its own scopes, or survive
   its own revocation. The grant is written under the tenant the session resolved, never under
   a tenant named in the request.
3. The code returns once, to the loopback listener, and is stored only as a digest. The CLI
   exchanges it, with the verifier, at `POST /oauth/token`.
4. The CLI stores the refresh token and presents short-lived bearer access tokens afterwards.

Token facts:

- Access tokens are signed claims verified without a database read. They last 15 minutes,
  which is also the window a revocation needs to take effect, since a signed token cannot be
  recalled early.
- Refresh tokens last 60 days and rotate: every exchange consumes the presented token and
  issues a new one. Presenting a consumed token means two parties hold the chain, so neither
  is trusted and the whole family is revoked; the user re-authorizes, and the theft becomes
  visible. That revocation runs in its own transaction, because the replayed request fails and
  a revocation written into the failing request's transaction would roll back with it.
- `POST /oauth/revoke` revokes a refresh token and its family deliberately.

## The Google connect flow

Connecting a Google calendar is a different relationship: syncr becomes Google's client, not
the user's. Three routes under `/api/v1/calendar-sources/google` run it:

- `POST .../google/connect` starts a connect. Its response is the disclosure, not a page: the
  three requested scopes with plain sentences for each, and which of the account's calendars
  will actually be read (the included ones, or none until the user includes one). The Settings
  screen renders this beside the button that opens the authorization URL.
- Google returns to `GET .../google/callback`, which redirects back to Settings with the
  outcome.
- `GET .../google/connection` reports whether Google is connected and raises every notice.

The three scopes are `calendarlist.readonly` (list calendars), `calendar.events.readonly`
(read included calendars' events), and `calendar.events.owned` (write the one calendar syncr
owns, which it reconciles destructively inside the projection horizon).

### State properties

The flow's `state` parameter makes the callback safe to act on. It carries the tenant it was
issued for, a timestamp, and a nonce, signed with an HMAC over a key derived for this purpose
alone from the deployment's signing secret. It is signed rather than stored, because a value
verified once, within minutes, by the same process that issued it does not need a table of
abandoned consents and a sweep.

Properties that make it safe:

- **Tenant-bound.** A state replayed while signed in as someone else fails the comparison.
- **Short-lived.** Accepted for 15 minutes either side of issue; a stale state is an abandoned
  flow, answered with "start it again".
- **Checked together with the session.** State proves this flow started here for this tenant;
  the session cookie proves who is asking now. Either alone is insufficient.
- **Versioned.** A state from an older format is refused by name rather than mis-parsed.

There is no PKCE here, on purpose: syncr is a confidential client toward Google, exchanging
the code with a client secret Google verifies, so an intercepted code cannot be redeemed.

### Token refresh

The stored refresh token is the standing authority and is kept encrypted at rest; an access
token lasts minutes and is never stored anywhere. During a sync pass, access tokens are held
in memory for the pass's life, so several Google sources cost one refresh rather than several.

Asking for an access token has four possible answers, and they are kept distinct because they
demand different responses:

- **Access granted.** Held in memory; the refresh timestamp is recorded.
- **No account connected.** Reading waits for a connect; ICS feeds are unaffected.
- **Grant dead** (revoked, undecryptable after a key rotation, or refused). Retrying cannot
  help. The failure and the instant it started are recorded, and the product raises its loudest
  non-blocking notice, banner and panel, whose first sentence is how long writes have been
  failing. The repair is a reconnect, offered from the notice.
- **Google unreachable.** The grant may be perfectly good; treating this as a dead grant would
  raise the expiry notice against healthy credentials until users learned to ignore it.

Reconnecting uses `access_type=offline` plus `prompt=consent`, so Google issues a new refresh
token even for an account that already granted the scopes. Without the second, a reconnect
meant to repair a dead credential would store nothing and change nothing.

## What each client ends up holding

| Client | Credential | Authority |
|---|---|---|
| Browser | Session cookie | All scopes, bounded by the session's lifetimes |
| CLI / agent | Bearer access token over a rotating refresh token | Only the granted scopes, revocable per family |
| Google | Encrypted refresh token syncr holds | Read the included calendars; write only the one calendar syncr owns |

Where these credentials land in storage, see [database.md](database.md). The routes themselves
are cataloged in [api.md](api.md).
