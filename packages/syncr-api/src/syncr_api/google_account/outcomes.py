"""How a connect ended, and where the browser goes to read about it.

The callback is a top-level navigation from Google, so its answer is a redirect rather than a
document: a problem-details body in the address bar is a blank page with JSON in it. The outcome
therefore travels as one query value from a closed set. **No screen reads that value today**, so
what a user sees on arrival is the durable read below and nothing about the attempt itself.

The set is closed for the same reason a rejection kind is: a screen states a different thing per
member, so a new member is a deliberate edit here and in whatever renders it, rather than a
free-text reason reaching a user through a URL. Google's own error code never reaches the address
bar for that reason: it is a value Google chooses the content of.

**The durable answer is not the query value.** ``GET .../connection`` is what Settings reads for
the state of the account, so a user who lands on Settings by any other route sees the same truth.
This says only how the attempt they just made ended.
"""

from __future__ import annotations

from typing import Final, Literal

# The path a completed connect returns to, on the origin the browser application is served from.
# Google matches a registered redirect URI as an exact string, so the callback is addressed at the
# api's own origin, and a host-relative Location would resolve there: on a stack that serves the
# application from a second origin, that names a path the api does not serve.
SETTINGS_PATH: Final = "/settings"
OUTCOME_QUERY_KEY: Final = "google"

type ConnectOutcome = Literal["connected", "denied", "expired", "failed"]
# The account is connected and every Google source will read on the next sync.
CONNECTED: Final[ConnectOutcome] = "connected"
# The user said no on Google's screen. Nothing is wrong and nothing changed.
DENIED: Final[ConnectOutcome] = "denied"
# The flow took too long, was started by another account, or could not be verified.
EXPIRED: Final[ConnectOutcome] = "expired"
# Google was asked and the exchange did not produce a grant syncr can store.
FAILED: Final[ConnectOutcome] = "failed"
CONNECT_OUTCOMES: Final = (CONNECTED, DENIED, EXPIRED, FAILED)


def settings_url(outcome: ConnectOutcome, *, app_base_url: str) -> str:
    """Where the browser goes once the callback has decided.

    ``app_base_url`` is the origin the application is served from, which the api is configured with
    rather than deriving from the request: the request arrived from Google at the api's own origin.
    """
    return f"{app_base_url.rstrip('/')}{SETTINGS_PATH}?{OUTCOME_QUERY_KEY}={outcome}"
