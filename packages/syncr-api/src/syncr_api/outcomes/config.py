"""The two route prefixes, the bound on how far back a count reads, and the wire bounds.

Two prefixes rather than one, because the routes address two different things. An outcome is
recorded on a BLOCK, which is the identity six mechanisms pair on, and a day is confirmed by its
local DATE, which is what the ledger renders. Neither is under the other on the wire: a block
belongs to a week, and the week a block belongs to cannot be recovered from its id.

``UNCONFIRMED_LOOKBACK_DAYS`` is the one bound worth arguing. The count of unconfirmed days is
rendered on both the Week and the Today surfaces, and the honest unbounded reading is "every past
day that holds a block and has not been answered for", which is a read over every revision the
tenant has ever stored on a request path with a 400 ms budget. Four weeks is bounded by what the
product's own late-confirmation case reaches: a user confirming three weeks late is the case
recorded in ticket 1144, so the window covers it with a week to spare. A day older than the window
can still be confirmed by naming it; what the window bounds is the COUNT, not the act.

``MAX_CONFIRM_RANGE_DAYS`` is the same figure for the same reason. The control that offers a
backfill states how many days it would settle, and that figure comes from the count above, so a
range wider than the count could be offered is a range the client could not have read.
"""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX

# `/api/v1/blocks`, built from the versioned prefix rather than written out.
BLOCKS_PREFIX: Final = f"{API_PREFIX}/blocks"
# `/api/v1/days`. Hyphenless and plural, matching every other collection path.
DAYS_PREFIX: Final = f"{API_PREFIX}/days"

# Relative to each router's own prefix. Path parameters are snake_cased, as every other path
# parameter this api declares is.
OUTCOME_PATH: Final = "/{block_id}/outcome"
DAY_PATH: Final = "/{date}"
CONFIRM_PATH: Final = "/{date}/confirm"
# Declared with no path parameter, so it cannot be read as a date. Two segments against the
# confirm route's three, so neither can match the other whatever order they are mounted in.
CONFIRM_RANGE_PATH: Final = "/confirm-range"

BLOCK_RESOURCE: Final = "block"
DAY_RESOURCE: Final = "day"

# How far back the count of unconfirmed days reads. Four weeks; see the module docstring.
UNCONFIRMED_LOOKBACK_DAYS: Final = 28

# How many days one backfill may settle. The same figure as the count that offers it.
MAX_CONFIRM_RANGE_DAYS: Final = 28

# The widest figure a `partial` outcome may report. A block is placed inside one week and the
# ledger lists it on the day it begins, so a report longer than a day describes something other
# than a block that ran short. The bound refuses that and refuses nothing a real block can hold:
# the longest one a template can declare is a night's sleep.
MAX_ACTUAL_MINUTES: Final = 24 * 60

# The wire field names the range body carries. `from` is a Python keyword, so the field is named
# `from_` and aliased here, which is the spelling the anchor span query already uses.
FROM_FIELD: Final = "from"
TO_FIELD: Final = "to"
