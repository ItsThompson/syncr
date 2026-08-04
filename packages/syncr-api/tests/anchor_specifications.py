"""The anchor-type specifications the settled records render, as one shared fixture.

`20-testing-strategy.md` names this the ``shadow_geometry`` fixture: the ``Interview``, ``Exam``,
and ``Lecture`` types with their real leads, durations, and buffers. It lives here rather than in
one test module because three suites want it -- the boundary rules, the reconciliation pass, and
the routes -- and the shadow generator will want it too.

**``LECTURE`` is the case the prep-collision rule must ACCEPT.** It has ``Pre 0m`` with a
30-minute transit, so the rule's guard on a non-zero prep duration is the only thing that lets it
exist. Without the guard this fixture cannot be built, which is why it is a fixture rather than
three literals inside one test.

``STANDUP`` is every member at zero: a type that casts no shadow at all, which is legal and is
what a recurring 15-minute meeting is typed as.

None of these carries a REAL Area, because an Area identifier only exists once a tenant has
declared one. The placeholders below stand in for the three the records name, and
:data:`DECLARED_AREAS` is the set a unit test passes to the rules as "the Areas this tenant
holds". A suite with a real tenant calls :func:`with_areas` to swap in identifiers it created.

Each declaration comes in two forms. The one the records render names no Area for its prep or its
legs, and an ``ATTRIBUTED_`` form names the ones ``block-states.html`` draws on those blocks. A
buffer with an Area is a block and a buffer without one is a forbidden window, so a suite reading
geometry wants both.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_api.anchors.config import FORBIDS_AREAS, FORBIDS_NOTHING
from syncr_api.anchors.records import AnchorTypeSpecification

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.identifiers import AreaId

# Stand-ins for the Areas `screens.html` names on these rows. Fixed rather than generated, so a
# failure message names the same identifier on every run.
CAREER: Final[AreaId] = UUID("aaaaaaaa-0000-4000-8000-000000000001")
STUDY: Final[AreaId] = UUID("aaaaaaaa-0000-4000-8000-000000000002")
TRANSIT: Final[AreaId] = UUID("aaaaaaaa-0000-4000-8000-000000000003")
DECLARED_AREAS: Final = frozenset({CAREER, STUDY, TRANSIT})

# A type that declares nothing at all, and the base every other fixture is built from. Every
# member is spelled out, so a field added to the specification is a deliberate edit here rather
# than a default nobody chose.
NOTHING: Final = AnchorTypeSpecification(
    name="Nothing",
    match_title_contains=None,
    match_source_id=None,
    prep_lead_minutes=0,
    prep_duration_minutes=0,
    prep_area_id=None,
    transit_lead_minutes=None,
    transit_duration_minutes=0,
    return_transit_minutes=0,
    transit_area_id=None,
    post_buffer_minutes=0,
    post_scope=FORBIDS_NOTHING,
    forbidden_area_ids=(),
)

# `screens.html`'s Interview row, and the worked example in `06-calendar-integration.md`:
# prep 10:00-10:30 and transit out 15:00-15:30 for a 16:00-16:45 anchor, no return leg, and
# recovery 16:45-18:00 forbidding Career and Study.
INTERVIEW: Final = replace(
    NOTHING,
    name="Interview",
    match_title_contains="Interview",
    prep_lead_minutes=360,
    prep_duration_minutes=30,
    transit_lead_minutes=60,
    transit_duration_minutes=30,
    return_transit_minutes=0,
    post_buffer_minutes=75,
    post_scope=FORBIDS_AREAS,
    forbidden_area_ids=(CAREER, STUDY),
)

# The Exam row: a 14-hour prep lead, which lands prep the evening before a 09:30 exam and
# possibly in the previous ISO week.
EXAM: Final = replace(
    NOTHING,
    name="Exam",
    match_title_contains="Exam",
    prep_lead_minutes=840,
    prep_duration_minutes=60,
    transit_lead_minutes=45,
    transit_duration_minutes=30,
    return_transit_minutes=30,
    post_buffer_minutes=60,
    post_scope=FORBIDS_AREAS,
    forbidden_area_ids=(STUDY,),
)

# The Lecture row: `Pre 0m`, `Transit 30m`, and a return leg. THE case the prep-collision rule
# must accept, because it has transit and no prep.
LECTURE: Final = replace(
    NOTHING,
    name="Lecture",
    match_title_contains="Lecture",
    prep_lead_minutes=0,
    prep_duration_minutes=0,
    transit_lead_minutes=None,
    transit_duration_minutes=30,
    return_transit_minutes=30,
    post_buffer_minutes=0,
    post_scope=FORBIDS_NOTHING,
)

# The Standup row: every member at zero, so it casts nothing.
STANDUP: Final = replace(NOTHING, name="Standup", match_title_contains="Standup")

# The three rendered types, in the order `screens.html` lists them.
SHADOW_GEOMETRY: Final = (INTERVIEW, EXAM, LECTURE)


def with_areas(
    specification: AnchorTypeSpecification,
    *,
    prep: AreaId | None = None,
    transit: AreaId | None = None,
    forbidden: Sequence[AreaId] = (),
) -> AnchorTypeSpecification:
    """``specification`` with real Area identifiers in place of the placeholders.

    The scope is left alone, so a caller swapping in real forbidden Areas keeps whichever scope
    the fixture declared and the biconditional still has to hold.
    """
    return replace(
        specification,
        prep_area_id=prep,
        transit_area_id=transit,
        forbidden_area_ids=tuple(forbidden),
    )


# The same three declarations with the Areas `block-states.html` renders on the blocks they cast:
# prep in the Area the commitment belongs to, and both legs in `Transit`. The forms above name no
# Area anywhere, so the same declarations cast forbidden WINDOWS instead of blocks. Both forms are
# needed because they are the two directions of one rule, and the recovery scope is untouched by
# either: the Areas a window forbids are not an Area a buffer belongs to.
ATTRIBUTED_INTERVIEW: Final = with_areas(
    INTERVIEW, prep=CAREER, transit=TRANSIT, forbidden=INTERVIEW.forbidden_area_ids
)
ATTRIBUTED_EXAM: Final = with_areas(
    EXAM, prep=STUDY, transit=TRANSIT, forbidden=EXAM.forbidden_area_ids
)
ATTRIBUTED_LECTURE: Final = with_areas(LECTURE, transit=TRANSIT)
ATTRIBUTED_GEOMETRY: Final = (ATTRIBUTED_INTERVIEW, ATTRIBUTED_EXAM, ATTRIBUTED_LECTURE)
