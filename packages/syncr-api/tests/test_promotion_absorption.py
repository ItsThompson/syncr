"""What a promotion can absorb, over every kind of content a pin can name.

The set is what matters here. A promotion MOVES the day-shape entry a pattern is about, so exactly
one kind of content has an entry to move, and the other six have to be answered rather than left to
a ``KeyError`` inside a request or to a sentence about something else.

**The totality is the type checker's**, through a ``match`` ending in ``assert_never``, and this
suite is the second half of that: mypy refuses an eighth ``BindingKind`` reaching the fallthrough,
and the sweep below refuses one whose answer is empty or whose words are another kind's.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from syncr_api.promotions.absorption import ABSORBABLE, accept_refusal
from syncr_domain.identity import BindingKind
from syncr_domain.promotion import PromotionRef

GYM = UUID(int=7)


def a_ref(kind: BindingKind, *, minute_of_day: int = 780) -> PromotionRef:
    return PromotionRef(kind=kind, entity_id=GYM, weekday=2, minute_of_day=minute_of_day)


class TestTheOneKindAPromotionCanActOn:
    def test_a_pattern_about_a_day_shape_entry_is_absorbable(self) -> None:
        assert accept_refusal(a_ref(BindingKind.TEMPLATE_ENTRY), title="Gym") is None

    def test_the_absorbable_kind_is_the_one_a_materialized_entry_binds(self) -> None:
        # A block that came from a day shape carries the ENTRY as its binding, whether the entry
        # names its content or leaves it to be bound at solve time. That is the whole reason a
        # promotion can move something: the candidate already names the entry.
        assert ABSORBABLE is BindingKind.TEMPLATE_ENTRY

    @pytest.mark.parametrize(
        "kind", [kind for kind in BindingKind if kind is not BindingKind.TEMPLATE_ENTRY]
    )
    def test_every_other_kind_is_refused_with_a_reason_naming_the_content(
        self, kind: BindingKind
    ) -> None:
        refusal = accept_refusal(a_ref(kind), title="Gym")

        assert refusal is not None
        assert "Gym" in refusal
        assert "Nothing was changed." in refusal


class TestWhatTheRefusalTellsTheReader:
    def test_content_a_shape_could_hold_points_at_declaring_an_entry(self) -> None:
        refusal = accept_refusal(a_ref(BindingKind.HABIT), title="Gym")

        assert refusal is not None
        assert "no entry to move" in refusal
        # The time is in the sentence, because the act it asks for needs it.
        assert "13:00" in refusal
        assert "Templates" in refusal

    def test_content_a_shape_cannot_hold_says_what_it_is_instead(self) -> None:
        # "Not a template entry" is not a reason a reader can act on, and neither of these can
        # become one: a day shape's entry binds a routine or a habit.
        task = accept_refusal(a_ref(BindingKind.TASK), title="Leetcode")
        anchor = accept_refusal(a_ref(BindingKind.ANCHOR), title="Standup")

        assert task is not None
        assert "your backlog" in task
        assert anchor is not None
        assert "calendar" in anchor
        assert "never authors" in anchor

    def test_the_four_kinds_a_shape_cannot_hold_do_not_share_one_sentence(self) -> None:
        # An anchor, its prep and its transit are three different things to be told.
        said = {
            accept_refusal(a_ref(kind), title="Standup")
            for kind in (
                BindingKind.TASK,
                BindingKind.ANCHOR,
                BindingKind.ANCHOR_PREP,
                BindingKind.ANCHOR_TRANSIT,
            )
        }

        assert len(said) == 4

    def test_a_caller_with_no_title_names_the_pattern_instead(self) -> None:
        # The accept route reads no window, so it holds no name: the sentence still has a subject.
        refusal = accept_refusal(a_ref(BindingKind.HABIT))

        assert refusal is not None
        assert "the content you keep pinning" in refusal

    def test_the_time_in_the_sentence_is_the_pattern_s_own(self) -> None:
        refusal = accept_refusal(a_ref(BindingKind.HABIT, minute_of_day=345), title="Gym")

        assert refusal is not None
        assert "05:45" in refusal
