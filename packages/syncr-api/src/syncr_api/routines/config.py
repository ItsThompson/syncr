"""The table name, the route paths, and the one bound that is this module's own.

Every bound on a routine's span lives in ``syncr_domain.routines`` rather than here, because
the span's invariants are the domain's: the schema reads them for its field bounds, the table
reads them for its check constraints, and one definition therefore cannot drift from the
other two.

The title bound is here, because it is not a span invariant. A routine's title is read in a
block label on the Week grid, which is as tight as an Area's name, and the frame is about 40%
of the blocks in a week.
"""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX

# `/api/v1/routines`, built from the versioned prefix rather than written out, so a change to
# the prefix reaches this module.
ROUTINES_PREFIX: Final = f"{API_PREFIX}/routines"
# Relative to the router's prefix. One member of the collection.
ROUTINE_PATH: Final = "/{routine_id}"

ROUTINES_TABLE: Final = "routines"

ROUTINE_RESOURCE: Final = "routine"

# A title is read in a block label, which the frame fills more of than anything else does.
ROUTINE_TITLE_MAX_LENGTH: Final = 60
