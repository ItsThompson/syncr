"""Where a verdict was computed, which is the one thing the arithmetic cannot carry.

Six members, and the two that are absent are absent for two different reasons.

``weekly_session`` was dropped because a session is a READ. A transition observed while the session
is open is caused by the pin that produced it, and that pin already carries
``session_mode_active = true`` from its caller, so a surface for the session would name the place a
row was noticed rather than the act that caused it.

``horizon`` was dropped because bringing a week into the horizon and re-probing one already in it
are the same loop, so both are ``maintainer``.

No member names a read. A read computes a verdict to render it and appends nothing, and the absence
of a member is what makes that structural rather than remembered: a read path has no surface to
record under.

Two facts about a surface live here rather than at its call sites, because both are read by code
that must not know which surface it is serving:

``provenance`` is how a surface reaches a verdict. Five of the six probe; only a completed solve
attempts a placement. Stated here so the row a surface writes can be refused when the two disagree,
and so the metric's label set is the reachable pairs rather than every combination.

``records_only_a_feasible_flip`` is ``VE8``. The maintainer's probe re-derives provenance from
arithmetic, so a tick after a solve would flip ``solver`` back to ``probe`` and the next solve would
flip it again, writing a row each time. A periodic re-confirmation is not a discovery.
"""

from __future__ import annotations

from enum import StrEnum

from syncr_domain.feasibility import Provenance


class VerdictSurface(StrEnum):
    """The six places a verdict transition is recorded from."""

    # A pin, unpin, drag, or keyboard move response.
    PIN = "pin"
    # Any other mutation's probe.
    MUTATION = "mutation"
    # A tradeoff request's probe.
    TRADEOFF = "tradeoff"
    # A completed solve, on the commit path.
    SOLVE = "solve"
    # A CLI mutation.
    CLI = "cli"
    # The horizon maintainer's periodic probe. TIME-DRIVEN.
    MAINTAINER = "maintainer"

    @property
    def provenance(self) -> Provenance:
        """The kind of check this surface reaches a verdict by."""
        return Provenance.SOLVER if self is VerdictSurface.SOLVE else Provenance.PROBE

    @property
    def records_only_a_feasible_flip(self) -> bool:
        """Whether a provenance change alone is a transition worth a row here."""
        return self is VerdictSurface.MAINTAINER


# The surface and provenance pairs a row can actually carry, which is one provenance per surface
# rather than every combination of the two. Read by the metric that seeds its label set: a series
# for a pair no writer can produce is a series an operator reads as "this never happens here".
REACHABLE_PAIRS = tuple((surface, surface.provenance) for surface in VerdictSurface)
