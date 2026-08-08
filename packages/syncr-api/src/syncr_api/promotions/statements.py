"""The words the two promotion routes state, composed here rather than on a surface.

The same discipline the pie review's ``statements`` and the Learned screen's ``gate_statements``
follow, and for the same reason: a figure or a claim spelled twice is one two surfaces can render
differently, and the whole justification for composing these server-side is that the words are the
api's.

A decline's sentence names the DATE it lapses rather than the number of weeks alone. "Not for three
months" is a duration a reader has to add to today; a date is the answer to the question they are
actually asking, which is whether this will interrupt them again soon.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.promotions.config import DECLINE_SUPPRESSION_WEEKS

if TYPE_CHECKING:
    from syncr_api.promotions.records import PromotionDeclineRecord
    from syncr_api.promotions.service import AcceptedPromotion


def accepted_statement(accepted: AcceptedPromotion) -> str:
    """What the accept changed, naming the shape, the old time and the new one.

    **A no-op says so.** An entry already at the pattern's time is reachable two ways: accepting the
    same pattern twice, and a reader who moved the entry by hand between the raise and the press.
    "Now places this at 13:00, where it was at 13:00" is a sentence that reads as a change and
    states none, on the one screen whose job is being checkable.
    """
    now_at = accepted.entry.span.target_time.isoformat("minutes")
    if accepted.entry.span.target_time == accepted.moved_from:
        return (
            f"Your {accepted.shape_name} shape already places this at {now_at}, so nothing "
            "changed. Every week from this one on was already being solved against that time."
        )
    return (
        f"Your {accepted.shape_name} shape now places this at {now_at}, where it was at "
        f"{accepted.moved_from.isoformat('minutes')}. Its duration and its flex band are "
        "unchanged, and every week from this one on will be solved against the new time. Past "
        "weeks keep the plan they were approved with."
    )


def declined_statement(declined: PromotionDeclineRecord) -> str:
    """That the pattern is silenced, until when, and that nothing was applied."""
    return (
        f"Nothing was changed in your templates. syncr will not raise this pattern again before "
        f"{declined.suppressed_until.date().isoformat()}, which is {DECLINE_SUPPRESSION_WEEKS} "
        "weeks, and it is how long the weekly session looks back: raising it again while the same "
        "weeks are still in view would be asking a question you have answered."
    )
