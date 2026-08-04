"""What an anchor type declares, and what a declaration has to satisfy. Pure, no database.

Four things are proven here, and each of them is a rule that would otherwise only be visible as a
wrong shadow on a grid weeks later.

**The three boundary rules, in both directions.** Every one of them is checked against the case it
must reject AND the case it must accept, because a rule that rejects everything passes a test that
only asserts rejection. The prep-collision rule's positive case is the one that matters:
``LECTURE`` has transit and no prep, so the guard on a non-zero prep duration is the only thing
that lets the rendered type exist.

**First match wins, and an override outranks it.** Ordering is what the whole typing model rests
on, and "the most specific match" is a comparison nobody can see.

**A publisher's values are bounded without merging two commitments.** A cut UID would map two
lectures onto one reconciliation key, so a long one is digested; a cut title only loses characters
nobody reads.

**An untyped anchor casts nothing.** Asserted as an answer the code gives rather than as an
absence a reader infers from a null identifier.
"""

from __future__ import annotations

from base64 import urlsafe_b64encode
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from syncr_api.anchors import matching, rules
from syncr_api.anchors.config import (
    ANCHOR_SPAN_DAYS_MAX,
    ANCHOR_TITLE_MAX_LENGTH,
    ANCHOR_TYPES_MAX,
    EXTERNAL_UID_MAX_LENGTH,
    FORBIDS_AREAS,
    FORBIDS_EVERYTHING,
    FORBIDS_NOTHING,
    RULE_MATCH,
    UNMATCHED,
    USER_OVERRIDE,
)
from syncr_api.anchors.identity import (
    UNTITLED,
    reconciliation_key,
    series_key,
    stored_location,
    stored_title,
)
from syncr_api.anchors.queries import decode_cursor, encode_cursor, read_span
from syncr_api.anchors.records import (
    AnchorRecord,
    AnchorTypeRecord,
    AnchorTypeSpecification,
    ShadowDeclaration,
)
from syncr_api.core.errors import Conflict, ValidationFailed
from syncr_domain.intervals import Interval
from tests.anchor_specifications import (
    CAREER,
    DECLARED_AREAS,
    EXAM,
    INTERVIEW,
    LECTURE,
    NOTHING,
    SHADOW_GEOMETRY,
    STANDUP,
    STUDY,
    TRANSIT,
)

SOURCE = uuid4()
ANOTHER_SOURCE = uuid4()
START = datetime(2026, 2, 10, 16, 0, tzinfo=UTC)


def a_type(specification: AnchorTypeSpecification, *, order: int = 0) -> AnchorTypeRecord:
    return AnchorTypeRecord(
        id=uuid4(), tenant_id=uuid4(), rule_order=order, specification=specification
    )


def an_anchor(
    *,
    title: str = "Kontron Placement Interview",
    series_uid: str | None = None,
    anchor_type_id: object = None,
    overridden: bool = False,
    source_id: object = SOURCE,
) -> AnchorRecord:
    return AnchorRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        source_id=source_id,  # type: ignore[arg-type]  # a bare UUID is the alias
        external_uid="uid@example.ac.uk",
        series_uid=series_uid,
        title=title,
        interval=Interval(START, START + timedelta(minutes=45)),
        location="Kontron, Ely",
        anchor_type_id=anchor_type_id,  # type: ignore[arg-type]  # a bare UUID is the alias
        type_overridden=overridden,
        possibly_stale=False,
    )


def validated(specification: AnchorTypeSpecification) -> None:
    """Every boundary rule, with the fixture's placeholder Areas taken as declared."""
    rules.validate(
        specification, declared_areas=DECLARED_AREAS, declared_sources={SOURCE, ANOTHER_SOURCE}
    )


# --------------------------------------------------------------------------------
# The rendered types. The whole fixture has to be constructible, or the tests that
# read it are testing something the product cannot express.
# --------------------------------------------------------------------------------


@pytest.mark.parametrize("specification", SHADOW_GEOMETRY, ids=lambda spec: spec.name)
def test_every_rendered_anchor_type_passes_the_boundary_rules(
    specification: AnchorTypeSpecification,
) -> None:
    validated(specification)


def test_a_transit_only_type_with_no_prep_is_accepted() -> None:
    # THE positive case for the prep-collision rule's guard. `Lecture` is `Pre 0m` with a
    # 30-minute transit, so without the guard on a non-zero prep duration the rule computes
    # `0 >= 0 + 30`, rejects it, and the rendered type cannot exist.
    assert LECTURE.prep_duration_minutes == 0
    assert LECTURE.transit_duration_minutes > 0

    rules.require_prep_clear_of_transit(LECTURE)


# --------------------------------------------------------------------------------
# Boundary rule one: an outbound leg that arrives after the anchor starts.
# --------------------------------------------------------------------------------


def test_a_transit_lead_shorter_than_its_journey_is_rejected() -> None:
    late = replace(NOTHING, transit_lead_minutes=20, transit_duration_minutes=30)

    with pytest.raises(ValidationFailed) as raised:
        rules.require_a_transit_lead_past_its_duration(late)

    assert [error.field for error in raised.value.errors or []] == ["transitLeadMinutes"]
    assert "30" in raised.value.detail


@pytest.mark.parametrize(
    ("lead", "duration"),
    [(30, 30), (60, 30), (None, 30), (0, 0), (None, 0)],
    ids=["abutting-explicitly", "arriving-early", "abutting-by-default", "no-leg", "neither"],
)
def test_a_transit_lead_at_least_its_journey_is_accepted(lead: int | None, duration: int) -> None:
    rules.require_a_transit_lead_past_its_duration(
        replace(NOTHING, transit_lead_minutes=lead, transit_duration_minutes=duration)
    )


# --------------------------------------------------------------------------------
# Boundary rule two: prep still running when the outbound leg leaves.
# --------------------------------------------------------------------------------


def test_a_prep_lead_that_collides_with_transit_is_rejected_naming_the_member() -> None:
    colliding = replace(
        NOTHING,
        prep_lead_minutes=60,
        prep_duration_minutes=30,
        transit_lead_minutes=60,
        transit_duration_minutes=30,
    )

    with pytest.raises(ValidationFailed) as raised:
        rules.require_prep_clear_of_transit(colliding)

    assert [error.field for error in raised.value.errors or []] == ["prepLeadMinutes"]
    # Names the figure to change and all three members that decide it, so the notice states
    # which one to move rather than only that something is wrong.
    assert "90" in raised.value.detail
    assert "prep lead" in raised.value.detail
    assert "transit lead" in raised.value.detail


def test_a_prep_lead_exactly_clear_of_transit_is_accepted() -> None:
    # The boundary itself: prep ends exactly as the outbound leg leaves. `>=` rather than `>`,
    # because half-open intervals do not overlap when one ends where the other starts.
    rules.require_prep_clear_of_transit(
        replace(
            NOTHING,
            prep_lead_minutes=90,
            prep_duration_minutes=30,
            transit_lead_minutes=60,
            transit_duration_minutes=30,
        )
    )


def test_the_prep_rule_reads_the_default_transit_lead_not_the_stored_null() -> None:
    # A null transit lead means abutting, so the journey's duration IS the lead the collision is
    # measured against. Reading the null as zero would accept a prep block that overlaps the leg.
    abutting = replace(
        NOTHING,
        prep_lead_minutes=45,
        prep_duration_minutes=30,
        transit_lead_minutes=None,
        transit_duration_minutes=30,
    )
    assert abutting.effective_transit_lead_minutes == 30

    with pytest.raises(ValidationFailed, match="60"):
        rules.require_prep_clear_of_transit(abutting)


# --------------------------------------------------------------------------------
# Boundary rule three: the three-way recovery choice.
# --------------------------------------------------------------------------------


def test_the_areas_scope_with_no_areas_is_rejected() -> None:
    empty = replace(NOTHING, post_buffer_minutes=75, post_scope=FORBIDS_AREAS)

    with pytest.raises(ValidationFailed) as raised:
        rules.require_a_scope_matching_its_areas(empty)

    assert [error.field for error in raised.value.errors or []] == ["forbiddenAreaIds"]
    assert "these Areas" in raised.value.detail


@pytest.mark.parametrize("scope", [FORBIDS_NOTHING, FORBIDS_EVERYTHING])
def test_a_scope_that_names_no_areas_is_rejected_when_it_names_some(scope: str) -> None:
    # The other half of the biconditional. An empty list once meant "forbids everything", so a
    # populated list under `all` or `none` is a request whose author believed the old reading.
    named = replace(
        NOTHING,
        post_buffer_minutes=75,
        post_scope=scope,  # type: ignore[arg-type]  # parametrized over the literal's members
        forbidden_area_ids=(CAREER,),
    )

    with pytest.raises(ValidationFailed) as raised:
        rules.require_a_scope_matching_its_areas(named)

    assert [error.field for error in raised.value.errors or []] == ["forbiddenAreaIds"]


@pytest.mark.parametrize(
    ("scope", "areas"),
    [
        (FORBIDS_NOTHING, ()),
        (FORBIDS_EVERYTHING, ()),
        (FORBIDS_AREAS, (CAREER,)),
        (FORBIDS_AREAS, (CAREER, STUDY)),
    ],
    ids=["nothing", "everything", "one-area", "two-areas"],
)
def test_a_scope_agreeing_with_its_areas_is_accepted(scope: str, areas: tuple[object, ...]) -> None:
    rules.require_a_scope_matching_its_areas(
        replace(
            NOTHING,
            post_scope=scope,  # type: ignore[arg-type]  # parametrized over the literal's members
            forbidden_area_ids=areas,  # type: ignore[arg-type]  # bare UUIDs are the alias
        )
    )


# --------------------------------------------------------------------------------
# The reference rules.
# --------------------------------------------------------------------------------


def test_every_member_naming_an_undeclared_area_is_reported() -> None:
    stranger = uuid4()
    naming = replace(
        NOTHING,
        prep_area_id=stranger,
        transit_area_id=TRANSIT,
        post_scope=FORBIDS_AREAS,
        forbidden_area_ids=(stranger,),
    )

    with pytest.raises(ValidationFailed) as raised:
        rules.require_declared_areas(naming, DECLARED_AREAS)

    # Both members that named the unknown Area, and NOT the one that named a declared Area.
    assert sorted(error.field for error in raised.value.errors or []) == [
        "forbiddenAreaIds",
        "prepAreaId",
    ]


def test_a_specification_naming_only_declared_areas_is_accepted() -> None:
    rules.require_declared_areas(
        replace(NOTHING, prep_area_id=CAREER, transit_area_id=TRANSIT), DECLARED_AREAS
    )


def test_a_match_rule_naming_an_unknown_source_is_rejected() -> None:
    with pytest.raises(ValidationFailed) as raised:
        rules.require_a_known_source(replace(NOTHING, match_source_id=uuid4()), {SOURCE})

    assert [error.field for error in raised.value.errors or []] == ["matchSourceId"]


def test_a_match_rule_naming_no_source_at_all_is_accepted() -> None:
    # A rule with no source matches every source, which is the ordinary case: it must not need a
    # source to exist before it can be written.
    rules.require_a_known_source(NOTHING, set())


def test_a_name_another_type_holds_is_refused() -> None:
    held = a_type(INTERVIEW)

    with pytest.raises(Conflict, match="name"):
        rules.require_an_unused_name("Interview", [held])


def test_a_type_may_keep_its_own_name() -> None:
    held = a_type(INTERVIEW)

    rules.require_an_unused_name("Interview", [held], apart_from=held.id)


def test_declaring_past_the_bound_on_anchor_types_is_refused() -> None:
    full = [a_type(replace(NOTHING, name=f"Type {index}")) for index in range(ANCHOR_TYPES_MAX)]

    rules.require_room_for_another_type(full[:-1])
    with pytest.raises(Conflict, match=str(ANCHOR_TYPES_MAX)):
        rules.require_room_for_another_type(full)


@pytest.mark.parametrize("missing", [0, 1], ids=["names-none", "names-one-of-two"])
def test_a_partial_rule_order_is_refused(missing: int) -> None:
    held = [a_type(INTERVIEW, order=0), a_type(LECTURE, order=1)]

    with pytest.raises(ValidationFailed) as raised:
        rules.require_a_total_order([row.id for row in held[:missing]], held)

    assert [error.field for error in raised.value.errors or []] == ["anchorTypeIds"]


def test_a_rule_order_naming_one_type_twice_is_refused() -> None:
    held = [a_type(INTERVIEW, order=0), a_type(LECTURE, order=1)]

    with pytest.raises(ValidationFailed):
        rules.require_a_total_order([held[0].id, held[0].id], held)


def test_a_permutation_of_the_types_held_is_accepted() -> None:
    held = [a_type(INTERVIEW, order=0), a_type(LECTURE, order=1)]

    rules.require_a_total_order([held[1].id, held[0].id], held)


# --------------------------------------------------------------------------------
# Matching: first match wins, and the override that outranks every rule.
# --------------------------------------------------------------------------------


def test_the_first_matching_rule_in_order_wins() -> None:
    broad = replace(NOTHING, name="Any interview", match_title_contains="Interview")
    first = a_type(broad, order=0)
    second = a_type(replace(NOTHING, name="Kontron", match_title_contains="Kontron"), order=1)

    matched = matching.first_match(
        [first, second], title="Kontron Placement Interview", source_id=SOURCE
    )

    assert matched == first.id


def test_reordering_the_same_two_rules_changes_which_one_wins() -> None:
    # The control for the test above. Without it, "the first match wins" passes on a pair whose
    # order does not matter.
    broad = replace(NOTHING, name="Any interview", match_title_contains="Interview")
    first = a_type(broad, order=0)
    second = a_type(replace(NOTHING, name="Kontron", match_title_contains="Kontron"), order=1)

    matched = matching.first_match(
        [second, first], title="Kontron Placement Interview", source_id=SOURCE
    )

    assert matched == second.id


@pytest.mark.parametrize(
    "title",
    ["Kontron Placement INTERVIEW", "kontron placement interview", "Interview"],
    ids=["shouted", "quiet", "exact"],
)
def test_a_title_rule_ignores_case(title: str) -> None:
    interview = a_type(INTERVIEW)

    assert matching.first_match([interview], title=title, source_id=SOURCE) == interview.id


def test_a_source_rule_matches_only_that_source() -> None:
    scoped = a_type(replace(LECTURE, match_source_id=SOURCE))

    assert matching.first_match([scoped], title="Lecture", source_id=SOURCE) == scoped.id
    assert matching.first_match([scoped], title="Lecture", source_id=ANOTHER_SOURCE) is None


def test_both_members_of_a_rule_have_to_hold() -> None:
    scoped = a_type(replace(NOTHING, match_title_contains="Lecture", match_source_id=SOURCE))

    assert matching.first_match([scoped], title="Standup", source_id=SOURCE) is None


def test_a_rule_stating_neither_member_matches_everything() -> None:
    catch_all = a_type(replace(NOTHING, name="Anything"))

    assert matching.first_match([catch_all], title="Whatever", source_id=SOURCE) == catch_all.id


def test_a_commitment_no_rule_matches_stays_untyped() -> None:
    assert matching.first_match([a_type(INTERVIEW)], title="Dentist", source_id=SOURCE) is None


def test_a_series_override_is_read_off_the_occurrences_that_carry_it() -> None:
    chosen = uuid4()
    held = [
        an_anchor(series_uid="standup@example", anchor_type_id=chosen, overridden=True),
        an_anchor(series_uid="lecture@example", anchor_type_id=uuid4(), overridden=False),
        an_anchor(series_uid=None, anchor_type_id=uuid4(), overridden=True),
    ]

    found = matching.series_overrides(held)

    # Only the overridden one with a series. A rule match contributes nothing, and an overridden
    # one-off has no series for a later occurrence to inherit through.
    assert found == {"standup@example": chosen}


def test_an_override_to_no_type_at_all_is_still_an_override() -> None:
    # "This standup is not an interview" is a decision. Present-with-None and absent are
    # different answers, and collapsing them would let a rule reclaim the series.
    held = [an_anchor(series_uid="standup@example", anchor_type_id=None, overridden=True)]

    found = matching.series_overrides(held)

    assert "standup@example" in found
    assert found["standup@example"] is None


# --------------------------------------------------------------------------------
# What a type declares, and what an untyped anchor casts.
# --------------------------------------------------------------------------------


def test_an_untyped_anchor_casts_no_shadow_of_any_kind() -> None:
    declared = ShadowDeclaration.of(None)

    assert declared.is_empty
    assert (
        declared.prep,
        declared.outbound_transit,
        declared.return_transit,
        declared.recovery,
    ) == (False, False, False, False)


def test_a_type_with_every_member_at_zero_casts_nothing_either() -> None:
    assert ShadowDeclaration.of(STANDUP).is_empty


@pytest.mark.parametrize(
    ("specification", "expected"),
    [
        (INTERVIEW, (True, True, False, True)),
        (EXAM, (True, True, True, True)),
        (LECTURE, (False, True, True, False)),
    ],
    ids=["interview", "exam", "lecture"],
)
def test_each_rendered_type_declares_the_products_its_record_shows(
    specification: AnchorTypeSpecification, expected: tuple[bool, bool, bool, bool]
) -> None:
    declared = ShadowDeclaration.of(specification)

    assert (
        declared.prep,
        declared.outbound_transit,
        declared.return_transit,
        declared.recovery,
    ) == expected


@pytest.mark.parametrize(
    ("buffer_minutes", "scope", "casts"),
    [
        (75, FORBIDS_AREAS, True),
        (75, FORBIDS_EVERYTHING, True),
        (75, FORBIDS_NOTHING, False),
        (0, FORBIDS_EVERYTHING, False),
    ],
    ids=["areas", "everything", "scope-none-collapses", "zero-buffer-collapses"],
)
def test_a_recovery_window_needs_both_a_buffer_and_a_scope(
    buffer_minutes: int, scope: str, casts: bool
) -> None:
    declared = ShadowDeclaration.of(
        replace(
            NOTHING,
            post_buffer_minutes=buffer_minutes,
            post_scope=scope,  # type: ignore[arg-type]  # parametrized over the literal's members
            forbidden_area_ids=(CAREER,) if scope == FORBIDS_AREAS else (),
        )
    )

    assert declared.recovery is casts


def test_the_areas_a_specification_names_are_reported_once_each() -> None:
    naming = replace(
        NOTHING,
        prep_area_id=CAREER,
        transit_area_id=TRANSIT,
        post_scope=FORBIDS_AREAS,
        forbidden_area_ids=(CAREER, STUDY),
    )

    # Career appears twice in the specification and once in the answer, so one existence read
    # covers every member and the reader is not asked to deduplicate.
    assert naming.referenced_area_ids == (CAREER, TRANSIT, STUDY)


@pytest.mark.parametrize(
    ("anchor_type_id", "overridden", "expected"),
    [
        (None, False, UNMATCHED),
        ("a type", False, RULE_MATCH),
        ("a type", True, USER_OVERRIDE),
        (None, True, USER_OVERRIDE),
    ],
    ids=["unmatched", "rule-match", "override", "override-to-nothing"],
)
def test_where_an_anchors_type_came_from_is_distinguishable(
    anchor_type_id: str | None, overridden: bool, expected: str
) -> None:
    resolved = None if anchor_type_id is None else uuid4()

    assert an_anchor(anchor_type_id=resolved, overridden=overridden).type_source == expected


# --------------------------------------------------------------------------------
# Bounding a publisher's values without merging two commitments.
# --------------------------------------------------------------------------------


def test_a_uid_that_fits_is_stored_exactly() -> None:
    uid = "0e1a2b3c-lecture@example.ac.uk"

    assert reconciliation_key(uid) == uid


def test_an_oversized_uid_is_digested_to_the_column_width() -> None:
    uid = "x" * (EXTERNAL_UID_MAX_LENGTH + 1)

    key = reconciliation_key(uid)

    assert len(key) == EXTERNAL_UID_MAX_LENGTH
    assert key != uid


def test_two_oversized_uids_sharing_a_prefix_stay_two_keys() -> None:
    # The reason a UID is digested rather than cut. Cutting these two would produce one key, so
    # two lectures would become one anchor that alternated between them on every sync.
    prefix = "y" * EXTERNAL_UID_MAX_LENGTH

    assert reconciliation_key(prefix + "-monday") != reconciliation_key(prefix + "-tuesday")


def test_a_digested_uid_is_the_same_key_on_every_run() -> None:
    # Reconciliation matches this week's read against last week's rows, so the mapping has to be
    # stable across processes, not merely injective within one.
    uid = "z" * (EXTERNAL_UID_MAX_LENGTH * 3)

    assert reconciliation_key(uid) == reconciliation_key(uid)


def test_a_series_uid_is_bounded_through_the_same_function() -> None:
    series = "s" * (EXTERNAL_UID_MAX_LENGTH + 10)

    assert series_key(None) is None
    assert series_key(series) == reconciliation_key(series)


@pytest.mark.parametrize(
    ("published", "stored"),
    [
        ("  Kontron Placement Interview  ", "Kontron Placement Interview"),
        ("Two\r\n\tlines", "Two lines"),
        ("", UNTITLED),
        ("   ", UNTITLED),
    ],
    ids=["trimmed", "collapsed", "empty", "whitespace"],
)
def test_a_title_is_trimmed_and_never_empty(published: str, stored: str) -> None:
    assert stored_title(published) == stored


def test_an_oversized_title_is_cut_rather_than_digested() -> None:
    assert len(stored_title("t" * (ANCHOR_TITLE_MAX_LENGTH * 2))) == ANCHOR_TITLE_MAX_LENGTH


@pytest.mark.parametrize(
    ("published", "stored"),
    [(None, None), ("", None), ("  ", None), (" Kontron, Ely ", "Kontron, Ely")],
    ids=["absent", "empty", "whitespace", "trimmed"],
)
def test_a_location_is_trimmed_or_absent(published: str | None, stored: str | None) -> None:
    assert stored_location(published) == stored


# --------------------------------------------------------------------------------
# Reading the list's query: a bounded span, and an opaque cursor.
# --------------------------------------------------------------------------------


def test_a_span_that_covers_time_is_read() -> None:
    span = read_span(START, START + timedelta(days=7))

    assert span == Interval(START, START + timedelta(days=7))


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (START, START),
        (START, START - timedelta(hours=1)),
        (START, START + timedelta(days=ANCHOR_SPAN_DAYS_MAX + 1)),
    ],
    ids=["zero-width", "reversed", "wider-than-the-bound"],
)
def test_a_span_that_covers_nothing_or_too_much_is_a_stated_rejection(
    start: datetime, end: datetime
) -> None:
    # A stated 422 rather than the domain error `Interval` raises, which nothing maps and which
    # would answer 500 to `?from=X&to=X`.
    with pytest.raises(ValidationFailed) as raised:
        read_span(start, end)

    assert [error.field for error in raised.value.errors or []] == ["to"]


def test_a_span_exactly_at_the_bound_is_read() -> None:
    read_span(START, START + timedelta(days=ANCHOR_SPAN_DAYS_MAX))


def test_a_cursor_round_trips_to_the_pair_it_names() -> None:
    anchor_id = uuid4()

    assert decode_cursor(encode_cursor((START, anchor_id))) == (START, anchor_id)


def test_no_cursor_reads_as_the_start_of_the_span() -> None:
    assert decode_cursor(None) is None


@pytest.mark.parametrize(
    "cursor",
    [
        "not base64 at all!",
        urlsafe_b64encode(b"one-part").decode().rstrip("="),
        urlsafe_b64encode(b"three|parts|here").decode().rstrip("="),
        urlsafe_b64encode(b"not-an-instant|" + str(uuid4()).encode()).decode().rstrip("="),
        urlsafe_b64encode(b"2026-02-10T16:00:00+00:00|not-a-uuid").decode().rstrip("="),
        urlsafe_b64encode(b"2026-02-10T16:00:00|" + str(uuid4()).encode()).decode().rstrip("="),
        urlsafe_b64encode(b"\xff\xfe").decode().rstrip("="),
        "A" * 400,
    ],
    ids=[
        "not-base64",
        "one-part",
        "three-parts",
        "not-an-instant",
        "not-a-uuid",
        "naive-instant",
        "not-utf8",
        "longer-than-the-bound",
    ],
)
def test_every_malformed_cursor_is_one_stated_rejection(cursor: str) -> None:
    with pytest.raises(ValidationFailed) as raised:
        decode_cursor(cursor)

    assert [error.field for error in raised.value.errors or []] == ["cursor"]
