"""The Google endpoints, the three scopes, the route paths, and the bounds.

**The scope set is recorded, not chosen here.** `docs/runbooks/google-oauth-verification.md`
holds the decision and its rejected alternatives; these three strings are that decision, and
changing the set invalidates whatever verification Google has granted. Each carries the plain
sentence the consent surface shows, because Google's own screen names the scope in its
vocabulary rather than in terms of what syncr will do with it.

**The callback path is fixed by the OAuth client's registration.** Google matches a redirect URI
as an exact string, so this value and the console's must agree character for character; the
process selects which registered URI it uses through ``GOOGLE_OAUTH_REDIRECT_URI``. Renaming
the constant is free, changing the path is a console edit.

**Every bound here answers a value Google chose the size of.** A token response, a page of
events, and a sync token are all as large as the provider makes them, and every one of them is
either stored in a bounded column or held in memory for the length of a sync pass.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from syncr_api.calendars.config import CALENDAR_SOURCES_PREFIX

GOOGLE_CREDENTIALS_TABLE: Final = "google_credentials"

# Relative to the calendar-sources prefix, which these three share: connecting an account is
# how a Google calendar source becomes readable, so it belongs to that resource rather than to
# a namespace of its own. The literal `google` segment sits where the sibling routes put
# `{source_id}`, and nothing collides because no sibling has this shape.
GOOGLE_PREFIX: Final = "/google"
CONNECT_PATH: Final = f"{GOOGLE_PREFIX}/connect"
CALLBACK_PATH: Final = f"{GOOGLE_PREFIX}/callback"
CONNECTION_PATH: Final = f"{GOOGLE_PREFIX}/connection"

# The full callback path, for the runbook's registered redirect URIs and for the test that
# asserts the route the console points at is the route the app serves.
CALLBACK_ROUTE: Final = f"{CALENDAR_SOURCES_PREFIX}{CALLBACK_PATH}"

ACCOUNT_RESOURCE: Final = "Google account"

# Google's own endpoints. Pinned rather than discovered: the discovery document would be one
# more network dependency on the connect path, and these have not moved in a decade.
AUTHORIZATION_ENDPOINT: Final = "https://accounts.google.com/o/oauth2/v2/auth"
# A published URL rather than a credential: the scanner matches the name, not the value.
TOKEN_ENDPOINT: Final = "https://oauth2.googleapis.com/token"  # noqa: S105

# The three scopes, verbatim. `calendarlist.readonly` is non-sensitive; the other two are
# sensitive, which is what caps an unverified app at 100 users.
CALENDAR_LIST_SCOPE: Final = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
EVENTS_READ_SCOPE: Final = "https://www.googleapis.com/auth/calendar.events.readonly"
EVENTS_OWNED_SCOPE: Final = "https://www.googleapis.com/auth/calendar.events.owned"
REQUESTED_SCOPES: Final = (CALENDAR_LIST_SCOPE, EVENTS_READ_SCOPE, EVENTS_OWNED_SCOPE)

# What each scope lets syncr do, in the user's terms rather than Google's. The consent surface
# renders these beside the scope strings, because "calendar.events.owned" tells a reader
# nothing about a destructive reconciliation.
SCOPE_STATEMENTS: Final[dict[str, str]] = {
    CALENDAR_LIST_SCOPE: (
        "See the list of calendars in your account, so you can choose which ones syncr reads."
    ),
    EVENTS_READ_SCOPE: (
        "Read events on the calendars you include, so your commitments become anchors the plan "
        "is built around. syncr never edits them."
    ),
    EVENTS_OWNED_SCOPE: (
        "Write to the one calendar you give syncr, which it reconciles destructively: anything "
        "syncr did not put there inside the projection horizon is removed."
    ),
}

# What the surface states about which calendars are read, for an account with no Google source
# configured yet. Naming the scopes without this would leave the honest question unanswered:
# the read scope reaches every calendar in the account, and what confines it is syncr.
NOTHING_IS_READ_YET = (
    "No calendar is read until you include it. After connecting, syncr lists the calendars in "
    "the account and you choose which become anchor sources; the rest are never read."
)

# `access_type=offline` is what makes Google issue a refresh token at all, and `prompt=consent`
# is what makes it issue a NEW one on a reconnect: without it, a second authorization of an
# account that already granted these scopes returns an access token and no refresh token, so a
# reconnect intended to repair a dead credential would store nothing and change nothing.
OFFLINE_ACCESS: Final = "offline"
FORCE_CONSENT: Final = "consent"
RESPONSE_TYPE_CODE: Final = "code"

# How long a state parameter is accepted. The user has to authenticate with Google and read a
# consent screen inside it, and a stale state is a flow somebody abandoned.
STATE_LIFETIME: Final = timedelta(minutes=15)
# Random bytes in the state's nonce. The state is signed, so the nonce only has to be
# unguessable, not long.
STATE_NONCE_BYTES: Final = 16

# How long one call to Google's token endpoint may take, whole. Not a per-operation timeout: a
# connect that hangs holds a request, and a refresh that hangs holds a worker tick.
TOKEN_TIMEOUT_SECONDS: Final = 10.0
# How much of a token response is read. A token endpoint answers in hundreds of bytes; this is
# the bound that stops a compromised or misconfigured host streaming into memory.
MAX_TOKEN_RESPONSE_BYTES: Final = 64 * 1024

# Column widths. A Google refresh token is around 100 characters and its ciphertext is longer,
# so the column is generous; the bound exists because the value is the provider's to size and
# an oversize write rolls back the whole transaction it is in.
ENCRYPTED_TOKEN_MAX_LENGTH: Final = 4_096
GRANTED_SCOPES_MAX_LENGTH: Final = 1_024
REFRESH_ERROR_MAX_LENGTH: Final = 500

# What a plaintext refresh token may be before it is encrypted. Bounded here so an oversize
# value is refused at the boundary that read it, naming the provider, rather than as a database
# error after the user has already consented in a browser.
REFRESH_TOKEN_MAX_LENGTH: Final = 2_048

# How long before expiry an access token is treated as spent. A token used at the moment it
# expires fails in flight, and a sync pass holds one across several calls.
ACCESS_TOKEN_SKEW: Final = timedelta(seconds=60)
# What lifetime is assumed when a token response states none. Google always states one; this is
# the floor that keeps a missing field from meaning "never expires".
DEFAULT_ACCESS_TOKEN_LIFETIME: Final = timedelta(minutes=5)
