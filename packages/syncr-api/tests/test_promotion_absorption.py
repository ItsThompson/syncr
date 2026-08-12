"""What a promotion can absorb, over every kind of content a pin can name.

The set is what matters here. A promotion MOVES the day-shape entry a pattern is about, so exactly
one kind of content has an entry to move, and the other six have to be answered rather than left to
a ``KeyError`` inside a request or to a sentence about something else.

**The totality is the type checker's**, through a ``match`` ending in ``assert_never``, and this
suite is the second half of that: mypy refuses an eighth ``BindingKind`` reaching the fallthrough,
and the sweep below refuses one whose answer is empty or whose words are another kind's.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final
from uuid import UUID

import pytest

from syncr_api.promotions import absorption
from syncr_api.promotions.absorption import ABSORBABLE, accept_refusal
from syncr_domain.identity import BindingKind
from syncr_domain.promotion import PromotionRef

GYM = UUID(int=7)

# A pointer to something outside this repository, in the two spellings this tree has carried: a bare
# ticket number and a story identifier. Neither resolves for a reader holding only the code.
_PLANNING_ARTIFACT: Final = re.compile(
    r"\btickets?\s*[/#]?\s*\d{1,4}\b|\b[A-Z]{1,3}-[A-Z]+-\d{1,3}\b"
)


def a_ref(kind: BindingKind, *, minute_of_day: int = 780) -> PromotionRef:
    return PromotionRef(kind=kind, entity_id=GYM, weekday=2, minute_of_day=minute_of_day)


def as_one_line(text: str) -> str:
    """Prose with its wrapping removed, because a sentence wraps wherever the column runs out."""
    return " ".join(text.split())


def pointers_in(text: str) -> list[str]:
    return _PLANNING_ARTIFACT.findall(text)


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
    @pytest.mark.parametrize("kind", [BindingKind.HABIT, BindingKind.ROUTINE])
    @pytest.mark.parametrize(("minute_of_day", "local_time"), [(780, "13:00"), (345, "05:45")])
    def test_content_a_shape_could_hold_is_answered_with_the_declaration_and_the_time(
        self, kind: BindingKind, minute_of_day: int, local_time: str
    ) -> None:
        # THE WHOLE SENTENCE, BY EQUALITY. The act it asks for is a declaration the reader makes
        # and it cannot be made without a time, so a reading over separate tokens would still pass
        # on a sentence that had lost one of the two, or gained a clause beside them. The expected
        # time is spelled out rather than read back off the ref the call is given.
        refusal = accept_refusal(a_ref(kind, minute_of_day=minute_of_day), title="Gym")

        assert refusal == (
            "No entry of your day shapes holds Gym, so there is no entry to move. "
            f"Declare one at {local_time} on Templates and the plan will start there. A template "
            "entry states a duration and a flex band that a pin says nothing about, which is why "
            "syncr proposes the pattern and leaves the declaration to you. Nothing was changed."
        )

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


class TestTheAnswerTheModuleRecords:
    """The decision the module states, and the pointer it must not state in place of one.

    The refusal is the product's answer and not a placeholder for a later one, so the module says
    which it is and these cases cross that. A statement no test reads can be deleted or reversed by
    anyone, which is how a refusal's reason comes to be a pointer at something a reader holding the
    code cannot open.
    """

    def test_the_module_states_that_accept_moves_an_entry_and_never_creates_one(self) -> None:
        stated = as_one_line(absorption.__doc__ or "")

        assert "Accept moves an entry and never creates one" in stated
        assert "the refusal below is that answer rather than a placeholder" in stated

    def test_the_module_states_what_a_created_entry_would_have_syncr_choose(self) -> None:
        stated = as_one_line(absorption.__doc__ or "")

        assert (
            "An entry declares a duration and a flex band that a pin states nothing about" in stated
        )

    def test_the_module_points_at_no_planning_artifact(self) -> None:
        assert pointers_in(_module_source()) == []

    def test_the_reading_that_finds_a_pointer_can_see_one(self) -> None:
        # The control on the case above. An emptiness assertion over a reading that matches nothing
        # passes whatever the module says, so both spellings the reading exists for are shown to
        # bite, and prose that carries neither is shown not to.
        assert pointers_in("the reason the template cannot take it") == []
        assert pointers_in("tickets/1550 holds the product question") == ["tickets/1550"]
        assert pointers_in("US-TPL-05's own example is a move") == ["US-TPL-05"]


def _module_source() -> str:
    path = absorption.__file__
    assert path is not None
    return Path(path).read_text(encoding="utf-8")
