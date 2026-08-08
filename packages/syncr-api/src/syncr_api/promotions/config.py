"""The two promotion routes, the table a decline writes, and how long a decline silences a pattern.

## The interval a decline suppresses for, and why it is a quarter

Section 11 says a decline "does not re-raise for a stated interval" and states no length; ticket
1530 recorded that choosing one without the screen that renders the raise would be choosing it
blind.

The length is the SESSION'S OWN WINDOW. A repeated pin is detected over the quarter of weeks the
weekly session reads, so the pattern a reader has just declined is still inside that read next week
and every week after it until it falls out. Anything shorter than the window therefore re-raises a
question the reader has answered while the evidence for it is unchanged, which is the nag the
product's severity discipline forbids. Anything longer would outlive the evidence: a pattern whose
weeks have all left the window is not raised at all, so suppressing beyond it silences nothing.

A quarter is also the one length "the period a review rests on" already has in this member, which is
what stops a reader meeting two different definitions of recent on one screen.
"""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX
from syncr_domain.budget_review import QUARTER_WEEKS

PROMOTION_DECLINES_TABLE: Final = "promotion_declines"

# `/api/v1/promotions`, built from the versioned prefix rather than written out.
PROMOTIONS_PREFIX: Final = f"{API_PREFIX}/promotions"

# Relative to the prefix above. The identifier is the candidate's own group, rendered by
# `PromotionRef.id`: nothing stores a candidate, so there is no minted key for one.
ACCEPT_PATH: Final = "/{promotion_id}/accept"
DECLINE_PATH: Final = "/{promotion_id}/decline"

PROMOTION_ID_FIELD: Final = "promotionId"
PROMOTION_RESOURCE: Final = "promotion candidate"

# How long a declined candidate is not raised for. See the module docstring for why it is the
# session's own window rather than a number chosen for this table.
DECLINE_SUPPRESSION_WEEKS: Final = QUARTER_WEEKS

# What `PromotionRef.id` can be at its longest: a kind, a UUID, a weekday and a minute of the day,
# with the three separators. A longer value is refused before it is parsed.
PROMOTION_ID_MAX_LENGTH: Final = 96
