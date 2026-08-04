"""How a connect ended, and where the browser goes to read about it.

The callback is a top-level navigation from Google, so its answer is a redirect rather than a
document: a problem-details body in the address bar is a blank page with JSON in it. The outcome
therefore travels as one query value from a closed set, and Settings renders the sentence for it.

The set is closed for the same reason a rejection kind is: the screen states a different thing per
member, so a new member is a deliberate edit here and in the copy that renders it, rather than a
free-text reason reaching a user through a URL. Google's own error code never reaches the address
bar for that reason: it is a value Google chooses the content of.

**The durable answer is not the query value.** ``GET .../connection`` is what Settings reads for
the state of the account, so a user who lands on Settings by any other route sees the same truth.
This says only how the attempt they just made ended.
"""

from __future__ import annotations

from typing import Final, Literal

# The path a completed connect returns to. Relative on purpose: the deployed stack serves the SPA
# and the api on one origin through the tunnel, so a relative Location resolves to the right host
# without a second base-URL setting to keep in step with the redirect URI Google holds.
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


def settings_url(outcome: ConnectOutcome) -> str:
    """Where the browser goes once the callback has decided."""
    return f"{SETTINGS_PATH}?{OUTCOME_QUERY_KEY}={outcome}"
