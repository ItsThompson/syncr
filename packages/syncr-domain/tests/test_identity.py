"""Block identity: the seven keys, the mapping between two vocabularies, and the derived id.

Four groups, and the third is the one the rest of the epic rests on.

**The two vocabularies.** Seven members each, three spelled differently, and one mapping
between them asserted total and injective in both directions. Without injectivity a block's
origin and its binding kind could not each determine the other, and both would have to be
stored.

**The key per kind.** One case per kind rather than only the habit-cadence case, because the
collision this key exists to prevent hits routines, template entries, and transit legs too.
Seven ``Sleep`` blocks in a week have seven ids; five ``Shower`` entries have five; an
anchor's two journeys differ by ``out`` and ``back``.

**The id is derived and nothing mints one.** Same week and same content, same id, whatever
order the blocks were built in. A key is validated against its kind by re-deriving it, so a
second spelling of a date and a digit that is not an ASCII digit are both refused: those are
the shapes that would otherwise make two parsers of one string disagree.

**What the key cannot be.** A key is derived from a closed vocabulary, so no text a person
or a publisher wrote can reach it. The refusals assert that with the bytes that have already
cost this repository one incident: a NUL, a C1 control, and a whitespace-only string.
"""

from __future__ import annotations

from datetime import date, timedelta
from itertools import permutations
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from syncr_domain.identity import (
    BLOCK_ID_LENGTH,
    INDEX_DIGITS,
    NO_OCCURRENCE,
    TASK_OCCURRENCE_KEY,
    BindingError,
    BindingKind,
    BindingRef,
    Origin,
    TransitLeg,
    binding_kind_of,
    block_id,
    date_occurrence_key,
    habit_occurrence_keys,
    index_occurrence_key,
    origin_of,
)
from syncr_domain.weeks import IsoWeek

WEEK = IsoWeek(2026, 7)
MONDAY = date(2026, 2, 9)

SLEEP = uuid4()
SHOWER_ENTRY = uuid4()
GYM = uuid4()
LEETCODE = uuid4()
INTERVIEW = uuid4()


def a_binding(kind: BindingKind) -> BindingRef:
    """One legal binding per kind, so a rule can be asserted over all seven."""
    match kind:
        case BindingKind.ROUTINE:
            return BindingRef.for_routine(SLEEP, on=MONDAY)
        case BindingKind.TEMPLATE_ENTRY:
            return BindingRef.for_template_entry(SHOWER_ENTRY, on=MONDAY)
        case BindingKind.HABIT:
            return BindingRef.for_habit(GYM, index=2)
        case BindingKind.TASK:
            return BindingRef.for_task(LEETCODE)
        case BindingKind.ANCHOR:
            return BindingRef.for_anchor(INTERVIEW)
        case BindingKind.ANCHOR_PREP:
            return BindingRef.for_anchor_prep(INTERVIEW)
        case BindingKind.ANCHOR_TRANSIT:
            return BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.OUT)


@st.composite
def a_generated_binding(draw: st.DrawFn) -> BindingRef:
    """A legal binding of any kind, built through the constructor its kind uses.

    Entities are drawn from a small pool so a generated set produces collisions to detect: with
    fresh UUIDs every time, "two bindings never share an id" would hold for a reason the
    derivation does not have to be right about.
    """
    kind = draw(st.sampled_from(list(BindingKind)))
    entity_id = draw(st.sampled_from((SLEEP, SHOWER_ENTRY, GYM, LEETCODE, INTERVIEW)))
    match kind:
        case BindingKind.ROUTINE | BindingKind.TEMPLATE_ENTRY:
            on = MONDAY + timedelta(days=draw(st.integers(min_value=0, max_value=6)))
            builder = (
                BindingRef.for_routine
                if kind is BindingKind.ROUTINE
                else BindingRef.for_template_entry
            )
            return builder(entity_id, on=on)
        case BindingKind.HABIT:
            return BindingRef.for_habit(
                entity_id, index=draw(st.integers(min_value=0, max_value=20))
            )
        case BindingKind.TASK:
            return BindingRef.for_task(
                entity_id,
                split_index=draw(st.none() | st.integers(min_value=0, max_value=8)),
            )
        case BindingKind.ANCHOR:
            return BindingRef.for_anchor(entity_id)
        case BindingKind.ANCHOR_PREP:
            return BindingRef.for_anchor_prep(entity_id)
        case BindingKind.ANCHOR_TRANSIT:
            return BindingRef.for_anchor_transit(
                entity_id, leg=draw(st.sampled_from(list(TransitLeg)))
            )


class TestTheTwoVocabularies:
    def test_an_origin_names_one_of_seven_things_a_block_can_be(self) -> None:
        # The grid, the ledger, and the CLI all render one of these, so the set is closed.
        assert [origin.value for origin in Origin] == [
            "frame",
            "template_entry",
            "habit",
            "task",
            "anchor",
            "prep",
            "transit",
        ]

    def test_a_binding_kind_names_one_of_seven_entities(self) -> None:
        assert [kind.value for kind in BindingKind] == [
            "routine",
            "template_entry",
            "habit",
            "task",
            "anchor",
            "anchor_prep",
            "anchor_transit",
        ]

    def test_the_mapping_is_total_in_both_directions(self) -> None:
        """Every kind has an origin and every origin has a kind. Neither set has a hole."""
        assert {origin_of(kind) for kind in BindingKind} == set(Origin)
        assert {binding_kind_of(origin) for origin in Origin} == set(BindingKind)

    def test_the_mapping_is_injective_in_both_directions(self) -> None:
        """What lets either vocabulary determine the other, so neither is stored twice.

        Totality alone would be satisfied by two kinds sharing one origin, which would make
        ``binding_kind_of`` a guess.
        """
        origins = [origin_of(kind) for kind in BindingKind]
        kinds = [binding_kind_of(origin) for origin in Origin]

        assert len(set(origins)) == len(origins)
        assert len(set(kinds)) == len(kinds)

    def test_each_vocabulary_is_the_inverse_of_the_other(self) -> None:
        for kind in BindingKind:
            assert binding_kind_of(origin_of(kind)) is kind
        for origin in Origin:
            assert origin_of(binding_kind_of(origin)) is origin

    @pytest.mark.parametrize(
        ("kind", "origin"),
        [
            (BindingKind.ROUTINE, Origin.FRAME),
            (BindingKind.ANCHOR_PREP, Origin.PREP),
            (BindingKind.ANCHOR_TRANSIT, Origin.TRANSIT),
        ],
        ids=["routine is the frame", "anchor_prep is prep", "anchor_transit is transit"],
    )
    def test_the_three_deliberate_spelling_differences(
        self, kind: BindingKind, origin: Origin
    ) -> None:
        """The binding names the entity; the origin names what the block is to the reader.

        These three differ on purpose, and a reader who assumes the two vocabularies are one
        set of strings would read the difference as a defect.
        """
        assert origin_of(kind) is origin
        assert kind.value != origin.value

    def test_the_four_kinds_that_are_spelled_the_same_are_spelled_the_same(self) -> None:
        same = {BindingKind.TEMPLATE_ENTRY, BindingKind.HABIT, BindingKind.TASK, BindingKind.ANCHOR}

        assert {kind for kind in BindingKind if kind.value == origin_of(kind).value} == same

    def test_a_binding_states_its_own_origin(self) -> None:
        """So a block carrying a binding needs no second field for what it is."""
        for kind in BindingKind:
            assert a_binding(kind).origin is origin_of(kind)


class TestTheKeyPerKind:
    def test_a_routine_is_keyed_by_the_local_date_it_materializes_on(self) -> None:
        assert BindingRef.for_routine(SLEEP, on=MONDAY).occurrence_key == "2026-02-09"

    def test_a_template_entry_is_keyed_by_the_local_date_too(self) -> None:
        assert BindingRef.for_template_entry(SHOWER_ENTRY, on=MONDAY).occurrence_key == "2026-02-09"

    def test_a_habit_is_keyed_by_the_zero_padded_occurrence_index(self) -> None:
        assert BindingRef.for_habit(GYM, index=2).occurrence_key == "02"
        assert index_occurrence_key(0) == "00"
        assert len(index_occurrence_key(0)) == INDEX_DIGITS

    def test_a_habit_index_past_the_padding_keeps_its_digits(self) -> None:
        """The padding is a spelling, not a width. Nothing orders keys lexicographically."""
        assert index_occurrence_key(100) == "100"

    def test_a_task_takes_one_key_and_its_chunks_differ_by_the_split_index(self) -> None:
        whole = BindingRef.for_task(LEETCODE)
        first, second = (BindingRef.for_task(LEETCODE, split_index=index) for index in (0, 1))

        assert whole.occurrence_key == TASK_OCCURRENCE_KEY == "00"
        assert first.occurrence_key == second.occurrence_key
        assert block_id(WEEK, first) != block_id(WEEK, second)

    def test_an_anchor_and_its_prep_carry_no_key_at_all(self) -> None:
        """One of each per anchor, so there is nothing for a key to separate."""
        assert BindingRef.for_anchor(INTERVIEW).occurrence_key == NO_OCCURRENCE == ""
        assert BindingRef.for_anchor_prep(INTERVIEW).occurrence_key == ""

    def test_an_anchors_two_journeys_are_keyed_out_and_back(self) -> None:
        out = BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.OUT)
        back = BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.BACK)

        assert (out.occurrence_key, back.occurrence_key) == ("out", "back")
        assert block_id(WEEK, out) != block_id(WEEK, back)

    def test_the_key_is_non_empty_for_every_kind_that_can_repeat_in_a_week(self) -> None:
        """I5 and X12, stated as the rule rather than as five separate examples.

        An anchor and its prep occur once each, so an empty key is the right answer for
        exactly those two and for nothing else.
        """
        once_per_week = {BindingKind.ANCHOR, BindingKind.ANCHOR_PREP}

        for kind in BindingKind:
            key = a_binding(kind).occurrence_key
            assert (key == "") is (kind in once_per_week), kind


class TestEveryKindThatRepeatsGetsItsOwnId:
    def test_seven_sleep_blocks_in_a_week_have_seven_ids(self) -> None:
        """Routines are ~40% of a week's blocks, so this is the ordinary case."""
        nights = [
            BindingRef.for_routine(SLEEP, on=MONDAY + timedelta(days=offset)) for offset in range(7)
        ]

        assert len({block_id(WEEK, night) for night in nights}) == 7

    def test_five_shower_template_entries_have_five_ids(self) -> None:
        showers = [
            BindingRef.for_template_entry(SHOWER_ENTRY, on=MONDAY + timedelta(days=offset))
            for offset in range(5)
        ]

        assert len({block_id(WEEK, shower) for shower in showers}) == 5

    def test_a_four_times_a_week_habit_has_four_ids(self) -> None:
        occurrences = [BindingRef.for_habit(GYM, index=index) for index in range(4)]

        assert len({block_id(WEEK, occurrence) for occurrence in occurrences}) == 4

    def test_one_anchor_casts_four_distinct_identities(self) -> None:
        """The commitment, its prep, and both journeys. Two of the four carry no key."""
        cast = [
            BindingRef.for_anchor(INTERVIEW),
            BindingRef.for_anchor_prep(INTERVIEW),
            BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.OUT),
            BindingRef.for_anchor_transit(INTERVIEW, leg=TransitLeg.BACK),
        ]

        assert len({block_id(WEEK, binding) for binding in cast}) == 4

    def test_a_split_task_has_one_id_per_chunk(self) -> None:
        chunks = [BindingRef.for_task(LEETCODE, split_index=index) for index in range(3)]

        assert len({block_id(WEEK, chunk) for chunk in chunks}) == 3


class TestTheIdIsDerived:
    def test_the_same_content_in_the_same_week_always_yields_the_same_id(self) -> None:
        """What lets a re-solve produce matching ids, and the classifier diff on them."""
        first = BindingRef.for_habit(GYM, index=1)
        second = BindingRef(BindingKind.HABIT, GYM, "01")

        assert block_id(WEEK, first) == block_id(WEEK, second)

    def test_the_same_content_in_another_week_yields_another_id(self) -> None:
        """A pin binds one week, and an outcome is a fact about one week's block."""
        binding = BindingRef.for_habit(GYM, index=1)

        assert block_id(WEEK, binding) != block_id(WEEK.following(), binding)

    def test_an_id_is_a_full_sha256_in_hex(self) -> None:
        """The width the column reserves for one. Stated so a shortening is a failing test."""
        derived = block_id(WEEK, a_binding(BindingKind.ROUTINE))

        assert len(derived) == BLOCK_ID_LENGTH
        assert set(derived) <= set("0123456789abcdef")

    def test_permuting_the_order_bindings_are_built_in_changes_no_id(self) -> None:
        bindings = [a_binding(kind) for kind in BindingKind]
        expected = {binding: block_id(WEEK, binding) for binding in bindings}

        for order in permutations(bindings):
            assert {binding: block_id(WEEK, binding) for binding in order} == expected

    @given(
        weeks=st.lists(st.integers(min_value=1, max_value=53), min_size=2, max_size=2, unique=True),
        indexes=st.lists(
            st.integers(min_value=0, max_value=200), min_size=2, max_size=2, unique=True
        ),
    )
    def test_two_identities_never_share_an_id(self, weeks: list[int], indexes: list[int]) -> None:
        """Every component reaches the digest, so no two of them collide by construction."""
        derived = {
            block_id(IsoWeek(2026, week), BindingRef.for_habit(entity, index=index))
            for week in weeks
            for entity in (GYM, LEETCODE)
            for index in indexes
        }

        assert len(derived) == 8

    @given(index=st.integers(min_value=0, max_value=500))
    def test_a_key_survives_the_round_trip_the_constructor_checks_it_with(self, index: int) -> None:
        binding = BindingRef.for_habit(GYM, index=index)

        assert BindingRef(BindingKind.HABIT, GYM, binding.occurrence_key) == binding

    @given(bindings=st.lists(a_generated_binding(), min_size=1, max_size=12))
    def test_distinct_content_never_shares_an_id(self, bindings: list[BindingRef]) -> None:
        """Over generated bindings of every kind, not only the habit case.

        The property the classifier's pairing rests on: two blocks pair if and only if they hold
        the same content instance. Every component of a binding reaches the digest, separated by
        a character none of them can contain, so the joined text determines the components.
        """
        derived = {binding: block_id(WEEK, binding) for binding in bindings}

        assert len(set(derived.values())) == len(set(bindings))

    @given(binding=a_generated_binding(), weeks=st.integers(min_value=1, max_value=52))
    def test_one_binding_in_two_weeks_is_two_ids(self, binding: BindingRef, weeks: int) -> None:
        """A pin binds one week and an outcome is a fact about one week's block."""
        assert block_id(IsoWeek(2026, weeks), binding) != block_id(IsoWeek(2027, weeks), binding)

    @given(binding=a_generated_binding())
    def test_deriving_an_id_twice_gives_one_answer(self, binding: BindingRef) -> None:
        """Nothing about a derivation depends on when it ran."""
        assert block_id(WEEK, binding) == block_id(WEEK, binding)


class TestTheKeyRulesRefuseWhatWouldNameAnotherBlock:
    @pytest.mark.parametrize(
        "key",
        [
            "2026-2-9",
            "2026-W07-1",
            "20260209",
            "2026-02-09T00:00:00",
            "tuesday",
            "",
            " 2026-02-09",
            "2026-02-09 ",
        ],
        ids=[
            "an unpadded month",
            "an ISO week date",
            "the basic format",
            "a date and a time",
            "a weekday name",
            "no key at all",
            "a leading space",
            "a trailing space",
        ],
    )
    @pytest.mark.parametrize(
        "kind", [BindingKind.ROUTINE, BindingKind.TEMPLATE_ENTRY], ids=["routine", "entry"]
    )
    def test_a_dated_kind_takes_exactly_one_spelling_of_a_date(
        self, kind: BindingKind, key: str
    ) -> None:
        """Two of these parse as dates and neither is the key.

        ``date.fromisoformat`` accepts the ISO week form and the basic form, so a check that
        only parsed would accept three spellings of one day and derive three ids for it. The
        constructor re-derives the key from what it parsed instead, which leaves one spelling.
        """
        with pytest.raises(BindingError, match="occurrence key"):
            BindingRef(kind, SLEEP, key)

    @pytest.mark.parametrize(
        "key",
        ["2", "0", "-1", "-01", "1_0", "٢", " 2", "02 ", "+02", "two", "", "0x2", "02.0"],
        ids=[
            "an unpadded index",
            "an unpadded zero",
            "a negative index",
            "a padded negative",
            "an underscore separator",
            "an Arabic-Indic digit",
            "a leading space",
            "a trailing space",
            "an explicit sign",
            "a word",
            "no key at all",
            "a hex literal",
            "a decimal point",
        ],
    )
    def test_a_habit_takes_exactly_one_spelling_of_an_index(self, key: str) -> None:
        """``int()`` reads five of these and every one of them re-derives to a different key.

        The Arabic-Indic digit is the case a hand-written ``isdigit`` check would accept:
        ``'٢'.isdigit()`` is true and ``int('٢')`` is 2, so the key would be stored in a
        spelling nothing else produces.
        """
        with pytest.raises(BindingError, match="occurrence key"):
            BindingRef(BindingKind.HABIT, GYM, key)

    @pytest.mark.parametrize(
        "key",
        ["0", "", "01", "00 ", "1"],
        ids=["unpadded", "empty", "the second", "a space", "one"],
    )
    def test_a_task_takes_one_demand_per_week_and_nothing_else(self, key: str) -> None:
        with pytest.raises(BindingError, match="occurrence key"):
            BindingRef(BindingKind.TASK, LEETCODE, key)

    @pytest.mark.parametrize(
        "kind", [BindingKind.ANCHOR, BindingKind.ANCHOR_PREP], ids=["anchor", "prep"]
    )
    @pytest.mark.parametrize(
        "key", ["00", " ", "out", "2026-02-09"], ids=["zero", "a space", "a leg", "a date"]
    )
    def test_a_once_per_anchor_kind_carries_no_key(self, kind: BindingKind, key: str) -> None:
        with pytest.raises(BindingError, match="occurrence key"):
            BindingRef(kind, INTERVIEW, key)

    @pytest.mark.parametrize(
        "key",
        ["", "OUT", "outbound", "return", "back ", "00"],
        ids=["empty", "shouted", "a longer word", "the wrong word", "a trailing space", "zero"],
    )
    def test_a_transit_block_goes_out_or_back(self, key: str) -> None:
        with pytest.raises(BindingError, match="occurrence key"):
            BindingRef(BindingKind.ANCHOR_TRANSIT, INTERVIEW, key)

    @pytest.mark.parametrize(
        "hostile",
        ["\x00", "2026-02-09\x00", "\x0002", "\x85", "\r\n", "   ", "\t"],
        ids=[
            "a NUL",
            "a date with a NUL",
            "a NUL before an index",
            "a C1 control",
            "a whitespace pair",
            "spaces",
            "a tab",
        ],
    )
    @pytest.mark.parametrize("kind", list(BindingKind), ids=[kind.value for kind in BindingKind])
    def test_no_kind_accepts_a_key_made_of_bytes_nobody_can_read(
        self, kind: BindingKind, hostile: str
    ) -> None:
        """A key comes from a closed derivation, so no publisher or user text can be one.

        The bytes here are the ones a mis-encoded feed manufactures: the api's own latin-1
        fallback maps every byte, so a NUL and a C1 control arrive with no hostility and no
        format violation. None of them can reach an identity, because none of them is a date,
        an index, ``'00'``, ``''``, or a leg.
        """
        with pytest.raises(BindingError, match="occurrence key"):
            BindingRef(kind, INTERVIEW, hostile)


class TestTheOrdinalsACadenceProduces:
    def test_a_habit_takes_the_leading_keys_of_one_sequence(self) -> None:
        assert habit_occurrence_keys(4) == ("00", "01", "02", "03")

    def test_reducing_a_cadence_from_four_to_three_drops_the_highest_ordinal(self) -> None:
        """The property that makes an already-recorded outcome safe against a cadence edit.

        Keyed by the day the solver happened to choose, the same reduction would re-key every
        survivor and an outcome recorded against one occurrence would name another.
        """
        four = habit_occurrence_keys(4)
        three = habit_occurrence_keys(3)

        assert set(four) - set(three) == {"03"}
        assert three == four[:3]

    def test_a_cadence_of_none_produces_no_keys(self) -> None:
        assert habit_occurrence_keys(0) == ()

    def test_a_negative_count_is_not_a_cadence(self) -> None:
        with pytest.raises(BindingError, match="cannot occur"):
            habit_occurrence_keys(-1)

    def test_a_negative_index_is_not_an_occurrence(self) -> None:
        with pytest.raises(BindingError, match="counts from zero"):
            index_occurrence_key(-1)

    def test_a_date_key_is_the_local_date_and_carries_no_zone(self) -> None:
        """The date is the one the block materializes on, resolved before this is called."""
        assert date_occurrence_key(date(2026, 3, 29)) == "2026-03-29"


class TestWhatASplitIndexBelongsTo:
    @pytest.mark.parametrize("kind", [kind for kind in BindingKind if kind is not BindingKind.TASK])
    def test_only_a_task_carries_a_chunk_number(self, kind: BindingKind) -> None:
        """Nothing else is splittable, so a chunk on one would change an id for no reason."""
        binding = a_binding(kind)

        with pytest.raises(BindingError, match="no split index"):
            BindingRef(kind, binding.entity_id, binding.occurrence_key, 0)

    def test_a_task_carries_one(self) -> None:
        assert BindingRef.for_task(LEETCODE, split_index=1).split_index == 1

    def test_a_chunk_number_counts_from_zero(self) -> None:
        with pytest.raises(BindingError, match="counts from zero"):
            BindingRef.for_task(LEETCODE, split_index=-1)

    def test_an_undivided_task_carries_none(self) -> None:
        assert BindingRef.for_task(LEETCODE).split_index is None


class TestTheGroupingPromotionDetectionUses:
    def test_the_content_key_drops_the_occurrence(self) -> None:
        """Pinning ``Gym`` to 13:00 for three weeks spans weeks and occurrences.

        So the occurrence is what has to fall out of the grouping, and nothing else does.
        """
        monday = BindingRef.for_habit(GYM, index=0)
        friday = BindingRef.for_habit(GYM, index=3)

        assert monday.content_key == friday.content_key
        assert monday != friday

    def test_two_entities_of_one_kind_group_apart(self) -> None:
        assert BindingRef.for_habit(GYM, index=0).content_key != (
            BindingRef.for_habit(uuid4(), index=0).content_key
        )

    def test_one_entity_read_two_ways_groups_apart(self) -> None:
        """An anchor's prep and its journey name the same anchor and are not one content."""
        shared: UUID = INTERVIEW

        assert (
            BindingRef.for_anchor_prep(shared).content_key
            != BindingRef.for_anchor_transit(shared, leg=TransitLeg.OUT).content_key
        )
