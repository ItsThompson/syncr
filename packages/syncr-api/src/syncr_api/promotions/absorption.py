"""What a promotion can absorb, and the sentence for a pattern it cannot.

**A promotion moves the template entry the pattern is about.** ``US-TPL-05``'s own example is a
move: "You have pinned Gym to 13:00 for three consecutive weeks. Move it in your Weekday
template?" A
block that materialized from a day shape carries that entry as its binding, so the entry is named by
the candidate itself and moving it needs nothing the pattern does not already state.

**Every other kind of content names nothing a day shape holds**, so there is no entry to move, and
inventing one is not the same act: an entry declares a duration and a band that a pin says nothing
about, and choosing them would be syncr deciding the shape of a reader's day rather than absorbing
what the reader did. So those patterns are still RAISED -- the pattern is real and worth stating --
and the raise carries the reason the template cannot take it and the one act that can.
``tickets/1550`` holds the product question of whether declaring the entry should be offered here.

**The set is closed by the type checker, not by a list.** The reason is chosen in a ``match`` ending
in :func:`assert_never`, so an eighth ``BindingKind`` is a mypy failure here rather than a candidate
whose accept answers with a sentence about something else, or a ``KeyError`` inside a request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, assert_never

from syncr_domain.identity import BindingKind

if TYPE_CHECKING:
    from syncr_domain.promotion import PromotionRef

# The one kind a promotion can act on: the block came from an entry of a day shape, and the entry is
# what the candidate names.
ABSORBABLE: Final = BindingKind.TEMPLATE_ENTRY


def accept_refusal(ref: PromotionRef, *, title: str | None = None) -> str | None:
    """Why the template cannot absorb this pattern, or ``None`` when it can.

    One statement, two readers: the weekly session renders it beside the raise so no accept control
    is drawn for a pattern the template cannot take, and the accept route raises it as a 409 for a
    caller that asked anyway. A second wording would let the screen and the route disagree about
    what the product will do.

    ``title`` is the name the reader knows the content by, where the caller has one. The session
    does, from the blocks of the weeks it read; the accept route does not, because it reads no
    window, and the sentence names the pattern instead.
    """
    subject = title if title is not None else "the content you keep pinning"
    match ref.kind:
        case BindingKind.TEMPLATE_ENTRY:
            return None
        case BindingKind.HABIT | BindingKind.ROUTINE:
            return (
                f"No entry of your day shapes holds {subject}, so there is no entry to move. "
                f"Declare one at {ref.local_time} on Templates and the plan will start there. A "
                "template entry states a duration and a flex band that a pin says nothing about, "
                "which is why syncr proposes the pattern and leaves the declaration to you. "
                "Nothing was changed."
            )
        case BindingKind.TASK:
            return _cannot_hold(subject, "finite work your backlog places against its deadline")
        case BindingKind.ANCHOR:
            return _cannot_hold(
                subject, "a commitment from a calendar syncr reads and never authors"
            )
        case BindingKind.ANCHOR_PREP:
            return _cannot_hold(
                subject, "preparation syncr derives from a commitment's own anchor type"
            )
        case BindingKind.ANCHOR_TRANSIT:
            return _cannot_hold(
                subject, "a journey syncr derives from a commitment's own anchor type"
            )
        case _:  # pragma: no cover - the type checker refuses an eighth kind reaching here
            assert_never(ref.kind)


def _cannot_hold(subject: str, what_it_is: str) -> str:
    """The refusal for content a day shape's entry cannot bind at all, naming what it is instead.

    What it is rather than what it is not: "not a template entry" is not a reason a reader can act
    on, and the four kinds that reach this each have a different answer.
    """
    return (
        f"A day shape's entry holds a routine or a habit, and {subject} is {what_it_is}, so your "
        "template has nothing to absorb this pattern into. Nothing was changed."
    )
