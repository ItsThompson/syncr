"""The degradation notice, and the one field rule the type enforces.

A notice tells a reader that something is degraded, how loudly to care, and what to do about
it. Volume is POSITION and pigment is KIND: they answer two different questions, so they are
two fields. There is no blocking volume, because syncr never blocks a reader over a
degradation.

``still_works`` may not be empty. Every degradation notice in this product names the
capability that survives, because a notice that says only what broke leaves a reader unable to
decide what to do next. The one shape that may name nothing is a total outage, and it says so
in ``is_whole_product_down`` rather than by carrying an empty list, so a reader of the code can
search for the exception rather than infer it.

The frontend's ``Notice`` narrows the wire's array to a non-empty tuple at its own boundary.
This is the other half of that pair: the validator here is what makes the array non-empty
before it is sent, so the narrowing at the far end never has a malformed notice to drop.

One action, at most. A reader asked to choose between two repairs has been given a decision
rather than a fix.
"""

from __future__ import annotations

from typing import Final, Literal, Self

from pydantic import Field, model_validator

from syncr_api.core.schemas import WireInstant, WireModel

type NoticeVolume = Literal["inline", "panel", "banner"]
INLINE: Final[NoticeVolume] = "inline"
PANEL: Final[NoticeVolume] = "panel"
BANNER: Final[NoticeVolume] = "banner"
NOTICE_VOLUMES: Final = (INLINE, PANEL, BANNER)

type NoticePigment = Literal["info", "amber", "oxide", "verdigris"]
INFO: Final[NoticePigment] = "info"
AMBER: Final[NoticePigment] = "amber"
OXIDE: Final[NoticePigment] = "oxide"
VERDIGRIS: Final[NoticePigment] = "verdigris"
NOTICE_PIGMENTS: Final = (INFO, AMBER, OXIDE, VERDIGRIS)


class NoticeAction(WireModel):
    """The single repair a notice offers."""

    label: str
    href: str


class NoticeScope(WireModel):
    """What the notice is about, where it is about one thing.

    ``date`` is the ONE day a notice is raised on and ``dates`` is every day it puts in doubt: the
    two answer different questions, so a surface reading one must not read the other. An inline
    notice on a day carries the first; a panel about a source that fed several days carries the
    second, which is what lets that surface mark a day without computing anything.
    """

    screen: str | None = None
    block_id: str | None = None
    source_id: str | None = None
    date: str | None = None
    dates: list[str] = Field(
        default_factory=list,
        description=(
            "Every day this condition puts in doubt, as ISO dates, earliest first. Empty when the "
            "condition affects no particular day, or when nothing is known to be affected."
        ),
    )


class Notice(WireModel):
    """One degradation, at one volume, naming what survives it."""

    id: str
    volume: NoticeVolume
    pigment: NoticePigment
    title: str
    detail: str
    unavailable: list[str] = Field(default_factory=list)
    still_works: list[str] = Field(
        description=(
            "The capabilities that remain. Never empty unless the whole product is down, "
            "because a notice that says only what broke leaves the reader unable to act."
        )
    )
    since: WireInstant | None = Field(
        default=None,
        description=(
            "How long the condition has held, as an instant. Null while it is not known. Typed "
            "as an instant rather than a string so it is serialized the way every other instant "
            "in this document is: one spelling per document, not two."
        ),
    )
    action: NoticeAction | None = None
    scope: NoticeScope | None = None
    is_whole_product_down: bool = False

    @model_validator(mode="after")
    def _refuse_a_notice_that_names_no_surviving_capability(self) -> Self:
        """Reject the shape the rule exists to forbid, rather than trusting each author."""
        if self.still_works or self.is_whole_product_down:
            return self
        message = (
            f"notice {self.id!r} names no surviving capability. Every degradation notice states "
            "what still works; a total outage declares itself with is_whole_product_down instead."
        )
        raise ValueError(message)
