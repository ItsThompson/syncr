"""What counts as a transition, and what a verdict looks like once it is one.

Two functions, both pure, and between them they hold every rule that decides whether a row exists.

## The verdict a row records is not the verdict field

``Verdict.feasible`` is refused at construction for a ``probe`` verdict, because capacity arithmetic
can prove a week impossible and can never prove one possible. So every probe verdict carries
``feasible = False``, and a row that copied the field would record every healthy week as broken and
open an infeasibility episode on every pin.

What a surface actually reports is what :func:`as_recorded` writes: whether a gap was found. A probe
that found none says so, a solver verdict says what it proved, and the episode a row opens is
therefore an episode the user was told about. The translation is here, once, because it is the one
place the domain's epistemics and the metric's substrate meet.

## What ``shortfall_minutes`` is

The LARGEST single gap, not the sum. Shortfalls can measure the same minutes twice: a deadline gap
and the floor gap of the Area the deadline belongs to are the same capacity seen two ways, so their
sum is not a duration the week is short by and can exceed the week itself. The largest gap is a real
quantity, and the figure the episode ratio reads is neither: it counts episodes.

``feasible`` and ``shortfall_minutes`` are derived here independently, and what requires them to
agree is the ``feasible_has_no_shortfall`` check constraint: a verdict reporting no gap has no
minutes to name, and one reporting a gap is not a week that holds its commitments.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.declarations import VerdictToRecord

if TYPE_CHECKING:
    from syncr_api.plans.records import VerdictEventRecord
    from syncr_api.plans.surfaces import VerdictSurface
    from syncr_domain.feasibility import ShortfallKind, Verdict
    from syncr_domain.identifiers import OperationId
    from syncr_domain.weeks import IsoWeek


def as_recorded(
    verdict: Verdict,
    *,
    iso_week: IsoWeek,
    surface: VerdictSurface,
    session_mode_active: bool,
    caused_by: OperationId | None = None,
) -> VerdictToRecord:
    """One verdict as the row that would record it, whether or not it is a transition."""
    return VerdictToRecord(
        iso_week=iso_week,
        occurred_at=verdict.computed_at,
        provenance=verdict.provenance,
        feasible=_was_reported_able_to_hold_its_commitments(verdict),
        shortfall_minutes=_largest_gap(verdict),
        shortfall_kinds=_kinds(verdict),
        surface=surface,
        session_mode_active=session_mode_active,
        input_version=verdict.input_version,
        caused_by_operation_id=caused_by,
    )


def is_a_transition(recorded: VerdictToRecord, *, since: VerdictEventRecord | None) -> bool:
    """Whether ``recorded`` says something this week's last recorded verdict did not. ``VE2``.

    ``since`` is the newest row this week holds, so a verdict recomputed identically answers
    ``False`` and a burst of twelve pins writes at most one row.

    **A week with no row at all is a week nobody has said anything about**, and the two surfaces
    read that differently. A mutation records the first verdict either way, which is what puts the
    baseline in the corpus at the moment a user first touches the week. The maintainer records only
    a discovery, so for it an absent row reads as "no episode is open", which is the same state a
    feasible row denotes: a periodic probe reporting that a week is fine is not a discovery, and
    ``VE8`` is the same argument applied to provenance.
    """
    if since is None:
        return not (recorded.surface.records_only_a_feasible_flip and recorded.feasible)
    if recorded.feasible != since.feasible:
        return True
    if recorded.surface.records_only_a_feasible_flip:
        # VE8. Its probe re-derives provenance from arithmetic, so recording a change in it would
        # write a row on the tick after every solve and another on the next solve, forever.
        return False
    # A provenance change while infeasible: the pair VE4 keeps, which is what lets the metric tell a
    # capacity warning from an authoritative finding. While feasible there is nothing to confirm.
    return not recorded.feasible and recorded.provenance is not since.provenance


def _was_reported_able_to_hold_its_commitments(verdict: Verdict) -> bool:
    """What the surface told the user, in the one field the episode definition is stated over."""
    return verdict.feasible or verdict.capacity_is_sufficient


def _largest_gap(verdict: Verdict) -> int:
    """The biggest single shortfall in minutes, and zero for a verdict carrying none."""
    return max((one.minutes for one in verdict.shortfalls), default=0)


def _kinds(verdict: Verdict) -> tuple[ShortfallKind, ...]:
    """The kinds this verdict names, deduplicated, in the order it named them.

    Two shortfalls of one kind are two gaps of the same sort, and the column answers which sorts
    the week hit rather than how many of each: ``dict.fromkeys`` keeps the first occurrence's
    position so two recordings of one verdict are equal by value.
    """
    return tuple(dict.fromkeys(one.kind for one in verdict.shortfalls))
