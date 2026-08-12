"""The occupancy rules: the five hard constraints that ask whether a span is already spent.

H1 to H4 and H13. Four of them ask whether anything at all may sit in the span, and H13 asks
whether this candidate's Area may, which is why it reads the same collection H2 does and is
stated beside it.

They are also the subset a plan derived from nothing else needs. Such a plan chooses no content,
sizes nothing and moves nothing, so the only way one of its placements can be illegal is that the
span is already spent: by an imported commitment, by a window that forbids every Area, by the
circadian frame, by something this same pass already placed, or by a window that forbids this
block's own Area.

Each rule is a function of a candidate and the state, and each answers with a rejection or with
nothing. They are collected in :data:`OCCUPANCY_RULES` in the hard-constraint table's own order, so
a candidate breaking two of them reports the first row it breaks rather than whichever check
happened to run first.

## An anchor's own derived blocks are exempt from that anchor's recovery window

A return leg and a recovery window both begin at ``anchor.end``, because recovery is measured from
the commitment rather than from the end of the journey home. So ``Go Home`` sits inside recovery by
construction, and without this exemption the one block a lecture reliably casts could never be
placed. The exemption is narrow in three ways, and each is what keeps it from excusing anything
else: it covers only the buffers an anchor derives, only against the ``recovery`` kind, and only
against the window that same anchor cast. Another commitment's recovery still forbids them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_domain.gaps import ForbiddenKind, ForbiddenScope
from syncr_domain.identity import BindingKind
from syncr_solver.constraints import Blocked, ConstraintRule
from syncr_solver.ordering import held_key

if TYPE_CHECKING:
    from syncr_domain.gaps import ForbiddenWindow
    from syncr_solver.constraints import Rule
    from syncr_solver.state import Held, PartialPlan, Placement

# What a rejection names when the span that rejected a candidate is a routine occurrence the
# preceding week owns. It carries no title of its own: the week that owns the occurrence holds the
# whole interval and materializes the one block, so this week has the span and not the name.
INHERITED_FRAME: Final = "a routine the preceding week owns"

# The kinds a commitment derives, which are the ones its own recovery window does not forbid. The
# commitment itself is not among them: an anchor is the space rather than a candidate inside it,
# and its recovery begins where it ends, so it could not overlap its own window anyway.
DERIVED_FROM_AN_ANCHOR: Final = frozenset({BindingKind.ANCHOR_PREP, BindingKind.ANCHOR_TRANSIT})


def anchor_overlap(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H1. An anchor is an immovable external fact, so a candidate gives way to it.

    It has no self-exemption, so an anchor offered at its own span is refused naming itself. Nothing
    reaches that: an anchor is the space rather than a candidate inside it, which is what a caller
    states by placing the anchors unchecked and offering everything derived from them here.
    """
    for anchor in state.anchors:
        if anchor.interval.overlaps(candidate.interval):
            return Blocked(ConstraintRule.ANCHOR_OVERLAP, candidate.interval, anchor.title)
    return None


def forbidden_window(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H2. A window forbidding every Area forbids this candidate whatever Area it carries.

    A window scoped to named Areas is H13's, and it is deliberately not read here: the two
    readings of one window drifting apart is the defect that split the field they arrive in.
    """
    for window in state.forbidden_windows:
        if window.scope is not ForbiddenScope.ALL:
            continue
        if window.interval.overlaps(candidate.interval) and not cast_by(window, candidate):
            return Blocked(ConstraintRule.FORBIDDEN_WINDOW, candidate.interval, window.label)
    return None


def frame_overlap(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H3. The frame bounds the day, at the effective duration the assembler clamped it to.

    It rejects against what the inputs carry, which is this week's own occurrences and the spans
    the preceding week's run into. A boundary-crossing span of any OTHER shape is occupancy nothing
    hands over, and the checker cannot reject a span no input names.
    """
    for entry in state.frame:
        if entry.interval.overlaps(candidate.interval):
            return Blocked(ConstraintRule.FRAME_OVERLAP, candidate.interval, entry.title)
    for span in state.inherited:
        if span.overlaps(candidate.interval):
            return Blocked(ConstraintRule.FRAME_OVERLAP, candidate.interval, INHERITED_FRAME)
    return None


def block_overlap(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H4. A solve never creates an overlap, which binds the solve rather than the plan.

    A user-authored overlap and an anchor landing on a planned block are both legitimate contents
    of a week. What this forbids is one placement of this solve overlapping another, or overlapping
    a span the week has already begun.

    So a candidate at the interval the user pinned it to is never refused here, whatever it lands
    on: the overlap it creates is the user's own, and refusing it would drop the pin rather than
    preserve the overlap. Every other candidate gives way, which is what makes an overlap in a
    solved week always either the user's or an external commitment's.

    **What the caller seeded is read first, and the week's own begun spans after it.** Both
    readings answer the same question, and a placement a caller stated carries the title the solve
    gave it, so a state holding one names it the way the rest of that solve's refusals do.
    """
    if state.pins.get(candidate.binding) == candidate.interval:
        return None
    for placement in state.placed:
        if placement.interval.overlaps(candidate.interval):
            return Blocked(ConstraintRule.BLOCK_OVERLAP, candidate.interval, placement.title)
    begun = _begun_over(candidate, state)
    if begun is None:
        return None
    return Blocked(ConstraintRule.BLOCK_OVERLAP, candidate.interval, begun.detail)


def _begun_over(candidate: Placement, state: PartialPlan) -> Held | None:
    """The span the week has already begun that this candidate would sit on, or nothing.

    Read from the state's own index rather than from what a caller passed, so a caller that seeds
    nothing cannot leave this rule unable to see time that has gone. The earliest of them when more
    than one qualifies, through the order those spans are held in, so a permuted input list cannot
    change which one a clause names.

    A candidate's OWN content is passed over. At the span that holds it, refusing would drop a
    block the week already has, and at any other span the refusal belongs to H10, which says the
    truer thing: the moment has passed.
    """
    return min(
        (
            held
            for binding, held in state.started.items()
            if binding != candidate.binding and held.interval.overlaps(candidate.interval)
        ),
        key=held_key,
        default=None,
    )


def forbidden_area(candidate: Placement, state: PartialPlan) -> Blocked | None:
    """H13. A window scoped to named Areas forbids those Areas and leaves every other one free.

    A candidate carrying no Area is the frame or an imported commitment, and both define the space
    rather than competing inside it, so a scoped window has no Area of theirs to name.
    """
    if candidate.area_id is None:
        return None
    for window in state.forbidden_windows:
        if window.scope is not ForbiddenScope.AREAS:
            continue
        if not window.forbids(candidate.area_id):
            continue
        if window.interval.overlaps(candidate.interval) and not cast_by(window, candidate):
            return Blocked(ConstraintRule.FORBIDDEN_AREA, candidate.interval, window.label)
    return None


def cast_by(window: ForbiddenWindow, candidate: Placement) -> bool:
    """Whether ``candidate`` is a buffer the commitment that cast this recovery window derived.

    One reading, shared by H2 and H13, because the exemption is a fact about the pair rather than
    about either rule: a window declared over every Area and the same window declared over named
    Areas must excuse the same block, or a user retyping one anchor would strand its journey home.
    """
    return (
        window.kind is ForbiddenKind.RECOVERY
        and candidate.binding.kind in DERIVED_FROM_AN_ANCHOR
        and candidate.binding.entity_id == window.anchor_id
    )


# The rules in force for a derived plan, in the table's own order. H13 is among them because a
# buffer carries an Area: a prep block for Career inside ANOTHER commitment's recovery window
# forbidding Career is a placement derivation determined and may not keep.
OCCUPANCY_RULES: Final[tuple[Rule, ...]] = (
    anchor_overlap,
    forbidden_window,
    frame_overlap,
    block_overlap,
    forbidden_area,
)
