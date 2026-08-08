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
    """What the accept changed, naming the shape, the old time and the new one."""
    entry = accepted.entry
    return (
        f"Your {accepted.shape_name} shape now places this at "
        f"{entry.span.target_time.isoformat('minutes')}, where it was at "
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
