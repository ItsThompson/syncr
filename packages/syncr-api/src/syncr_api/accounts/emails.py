"""Email normalization, so one person is one identity.

``Sam@Example.com`` and ``sam@example.com`` are the same account. The rule is stated
once, here, and applied by both sign-in and account creation: normalizing in a request
schema instead would leave the bootstrap path free to store a form that sign-in can
never match.

Only case and surrounding whitespace are touched. The local part of an address is
case-sensitive per the RFC, and mail providers ignore that in practice; lowercasing
both parts is the behavior every user expects, and the alternative is an account that
cannot be signed in to because of a capital letter.
"""

from __future__ import annotations


def normalize_email(raw: str) -> str:
    """The canonical stored and compared form of an email address."""
    return raw.strip().lower()
