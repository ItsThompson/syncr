"""Session lifetimes, the cookie's shape, and the route prefix.

The two lifetimes are separate rules and both are needed. The idle window is what
makes a session survive a reload, an overnight gap, and a browser restart without
asking for a password again. The absolute lifetime is what makes an abandoned session
die without the user doing anything: without it, a session used once a fortnight
forever is a session that never expires, which is a credential with no end date.

Sliding is throttled. Writing ``last_seen_at`` on literally every request would put a
write on the read path of a product whose interactive budget is measured in
milliseconds, and a minute of resolution is more than the idle window needs.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Literal

# Sign-in and the session it establishes sit OUTSIDE the versioned domain prefix,
# alongside `/oauth` and `/.well-known`: they are how a caller obtains the credential
# every versioned route requires, so they are not themselves versioned resources.
# This is a sibling of `syncr_api.core.settings.API_PREFIX` rather than something
# derived from it, because there is nothing in `/api/v1` to derive `/auth` from.
AUTH_PREFIX = "/auth"

SESSION_COOKIE_NAME = "syncr_session"
# `Lax` and not `Strict`: the sign-in redirect returns the user to the route they
# asked for, and `Strict` withholds the cookie on that top-level navigation, so the
# user would land signed out on the page they were just sent to. `Lax` withholds it
# from cross-site unsafe requests, which is the case CSRF actually needs, and the
# origin check covers the rest.
SESSION_COOKIE_SAME_SITE: Literal["lax"] = "lax"
SESSION_COOKIE_PATH = "/"

# How long a session survives without being used.
SESSION_IDLE_TIMEOUT = timedelta(days=14)
# The cap the idle window is never allowed to push past.
SESSION_ABSOLUTE_LIFETIME = timedelta(days=90)
# The minimum age of `last_seen_at` before a use rewrites it.
SESSION_SLIDE_INTERVAL = timedelta(minutes=1)

# A bootstrapped account is the only account, and it is reachable from the public
# internet through the tunnel, so the one password guarding it has a floor.
MINIMUM_PASSWORD_LENGTH = 12

# RFC 5321 caps a forward path at 320 characters. Both the column and the request
# schema are bounded by it, from here, so a hostile body cannot store an unbounded
# string and the two bounds cannot drift apart.
EMAIL_MAX_LENGTH = 320
# scrypt's encoded form is well under this; the bound exists for the same reason.
PASSWORD_HASH_MAX_LENGTH = 256
