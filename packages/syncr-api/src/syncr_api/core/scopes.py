"""The authority vocabulary: three scopes, and how a scope string is read and written.

Coarse and few, deliberately. A finer set would need a rule per endpoint, and the only
bearer client is a command-line tool whose whole surface is "read the plan" and "change
the plan"; splitting `plan:write` into a pin scope and an approve scope would give an
operator four checkboxes to reason about and an attacker no fewer doors.

A browser session carries every scope, because the user is acting directly: there is no
third party to withhold authority from. A bearer token carries the subset its grant was
issued for, which is what makes a stolen CLI token less than a stolen password.

This module holds the vocabulary only. Who may act is
:mod:`syncr_api.core.principal`, which is also where the one scope check lives, so a
service imports one module to authorize rather than two.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# What separates scopes in a scope string, per RFC 6749: one space, and any run of
# whitespace reads as one separator.
SCOPE_SEPARATOR = " "


class Scope(StrEnum):
    """One coarse capability a credential may carry."""

    PLAN_READ = "plan:read"
    PLAN_WRITE = "plan:write"
    ADMIN = "admin"


# Every scope, in the order the consent screen and the discovery document list them:
# widening, so a reader sees the least authority first.
SCOPE_ORDER: tuple[Scope, ...] = (Scope.PLAN_READ, Scope.PLAN_WRITE, Scope.ADMIN)
ALL_SCOPES: frozenset[Scope] = frozenset(SCOPE_ORDER)

# What each scope grants, in the words a consent screen shows. The consent table, in
# one place, because a screen that renders a raw `plan:write` is asking the user to
# consent to a string.
SCOPE_DESCRIPTIONS: dict[Scope, str] = {
    Scope.PLAN_READ: "Read your weeks, plans, blocks, backlog, verdicts, and operations.",
    Scope.PLAN_WRITE: (
        "Pin and move blocks, confirm days, approve proposals, capture tasks, and record outcomes."
    ),
    Scope.ADMIN: "Change calendar sources, the write target, budgets, templates, and settings.",
}


def parse_scopes(raw: str | None) -> frozenset[Scope] | None:
    """The scopes ``raw`` names, or ``None`` when any of them is not a scope we serve.

    ``None`` rather than a raised error, so the caller decides which protocol error an
    unknown scope becomes: the authorize endpoint and the token endpoint answer
    differently, and this module knows about neither.
    """
    if raw is None:
        return None
    names = raw.split()
    known = {scope.value for scope in Scope}
    if not names or any(name not in known for name in names):
        return None
    return frozenset(Scope(name) for name in names)


def format_scopes(scopes: Iterable[Scope]) -> str:
    """The scope string for ``scopes``, ordered so two equal sets render identically.

    Stable ordering is what lets a test compare a scope string, and what stops a
    response body from changing between two runs that granted the same authority.
    """
    held = set(scopes)
    return SCOPE_SEPARATOR.join(scope.value for scope in SCOPE_ORDER if scope in held)
