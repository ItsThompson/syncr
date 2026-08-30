"""The ``state`` parameter: signed, tenant-bound, and short-lived.

``state`` is what makes the callback safe to act on. Without it, a browser that arrives carrying
somebody else's authorization code would have that account connected to whoever is signed in, and
the flow would look like it worked.

**The state is signed rather than stored.** It carries the tenant it was issued for and when, and
an HMAC over both under the deployment's signing secret. A table would need a row per abandoned
consent and a sweep to remove them, for a value that is verified once, within minutes, by the same
process that issued it.

**The callback checks the state AND the session.** The state proves this flow started here for
this tenant; the session cookie proves who is asking now. Either alone is insufficient: a state
replayed into a different account fails the comparison, and a session with no state is a callback
nobody started.

**The signing secret is derived, not reused.** The session secret signs session identifiers, and a
value signed under one key for two purposes is a value one purpose can forge for the other. A
per-use key from HKDF-like derivation costs one hash and closes that.

No PKCE. syncr is a confidential client here: the code is exchanged with a client secret Google
verifies, so a code intercepted at the browser cannot be redeemed. A separate case exists for
adding it anyway, which needs the verifier to survive the round trip.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_api.google_account.config import STATE_LIFETIME, STATE_NONCE_BYTES

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.identifiers import TenantId

# The version prefix. A state issued by an older shape is refused by name rather than
# mis-parsed, so changing the format costs one abandoned consent rather than a confusing failure.
_VERSION: Final = "v1"
_SEPARATOR: Final = "."
_FIELD_COUNT: Final = 5

# What the derived key is derived FOR. Any other purpose derives a different key, so a state
# cannot be presented as a session identifier or the reverse.
_KEY_PURPOSE: Final = b"syncr.google_account.state.v1"

_DIGEST: Final = hashlib.sha256


@dataclass(frozen=True, slots=True)
class StateAccepted:
    """The state verified, and the tenant it was issued for."""

    tenant_id: TenantId


@dataclass(frozen=True, slots=True)
class StateRejected:
    """The state did not verify, and why, in words a panel can render."""

    reason: str


type StateVerdict = StateAccepted | StateRejected


def issue_state(*, tenant_id: TenantId, secret: str, at: datetime) -> str:
    """A signed state binding this connect flow to one tenant and one moment."""
    payload = _SEPARATOR.join(
        (_VERSION, tenant_id.hex, str(int(at.timestamp())), secrets.token_hex(STATE_NONCE_BYTES))
    )
    return f"{payload}{_SEPARATOR}{_sign(payload, secret)}"


def read_state(state: str, *, secret: str, now: datetime) -> StateVerdict:
    """The tenant ``state`` was issued for, or why it is not acceptable.

    The signature is checked before anything is read out of the value, so a forged state cannot
    reach the expiry comparison or the identifier parse.
    """
    payload, _, presented = state.rpartition(_SEPARATOR)
    if not payload or not hmac.compare_digest(presented, _sign(payload, secret)):
        return StateRejected("the connect flow could not be verified, so nothing was connected")
    fields = state.split(_SEPARATOR)
    if len(fields) != _FIELD_COUNT or fields[0] != _VERSION:
        return StateRejected("the connect flow was started by an older version of syncr")
    return _within_lifetime(fields[1], fields[2], now=now)


def _within_lifetime(tenant: str, issued: str, *, now: datetime) -> StateVerdict:
    """The tenant a verified state names, once its age and shape are acceptable."""
    try:
        tenant_id = UUID(hex=tenant)
        issued_at = int(issued)
    except ValueError:
        # Unreachable through a signed state, because this process wrote both fields. Answered
        # rather than raised so a malformed value cannot become a 500 on the callback.
        return StateRejected("the connect flow could not be read, so nothing was connected")
    age = int(now.timestamp()) - issued_at
    # Bounded in both directions. A future-dated state is unreachable through one this deployment
    # signed, but the comparison is symmetric for one comparison's cost, and a clock that moved
    # backwards across a restart is the reachable way to get one.
    if age > STATE_LIFETIME.total_seconds() or age < -STATE_LIFETIME.total_seconds():
        minutes = int(STATE_LIFETIME.total_seconds() // 60)
        return StateRejected(
            f"the connect flow was not started within the last {minutes} minutes. Start it again; "
            "nothing was connected and every calendar syncr already reads still works"
        )
    return StateAccepted(tenant_id=tenant_id)


def _sign(payload: str, secret: str) -> str:
    return hmac.new(_derived_key(secret), payload.encode("utf-8"), _DIGEST).hexdigest()


def _derived_key(secret: str) -> bytes:
    """A key for this purpose alone, derived from the deployment's signing secret."""
    return hmac.new(secret.encode("utf-8"), _KEY_PURPOSE, _DIGEST).digest()
