"""The bounds, the table name, and the route paths the off-plan routes read.

One bound is worth a word. A label is the user's own words rendered in the gutter beside a
hatched band, which is a narrow space, so it is bounded well below what a title field would
be. The bound rejects a paragraph pasted into a name field rather than describing anything
about time off.
"""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX

# `/api/v1/off-plan`, built from the versioned prefix rather than written out, so a change to
# the prefix reaches this module. Hyphenated on the wire, matching every other multi-word path.
OFF_PLAN_PREFIX: Final = f"{API_PREFIX}/off-plan"
# Relative to the router's prefix. One member of the collection.
OFF_PLAN_PATH: Final = "/{period_id}"

OFF_PLAN_TABLE: Final = "off_plan_periods"

OFF_PLAN_RESOURCE: Final = "off-plan period"

# Read in a gutter label beside the span, which is tight.
LABEL_MAX_LENGTH: Final = 60
# A span with no name says so with null, so the empty string is refused rather than stored as a
# second spelling of it. This is the bound five sibling schemas already carry on a user-authored
# name; what a whitespace-only value should become is one shared decision and is not made here.
LABEL_MIN_LENGTH: Final = 1
