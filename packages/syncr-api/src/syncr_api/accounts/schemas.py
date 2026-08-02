"""The wire shapes sign-in and the session endpoint exchange.

Explicit schemas, never a mapped row: an ORM object serialized directly would put
``password_hash`` one attribute away from a response, and would make every added
column a silent contract change.

The token is absent from every shape here on purpose. It travels in the ``Set-Cookie``
header and nowhere else, so no response body, log line, or generated TypeScript type
can carry it.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - pydantic resolves annotations at runtime
from uuid import UUID  # noqa: TC003 - pydantic resolves annotations at runtime

from pydantic import Field

from syncr_api.accounts.config import EMAIL_MAX_LENGTH
from syncr_api.core.schemas import WireModel

# A password is not validated for shape at sign-in: the only question is whether it
# matches, and a rule here would be a second source of truth for whatever the
# bootstrap command accepted. Bounded so an unbounded body cannot reach the key
# derivation, which is deliberately expensive.
PASSWORD_MAX_LENGTH = 1024


class LoginRequest(WireModel):
    """Credentials presented to establish a session."""

    email: str = Field(min_length=3, max_length=EMAIL_MAX_LENGTH)
    password: str = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


class SessionResponse(WireModel):
    """The current principal, and when this session stops working."""

    tenant_id: UUID
    user_id: UUID
    email: str
    expires_at: datetime
