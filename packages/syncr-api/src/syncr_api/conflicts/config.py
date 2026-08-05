"""The two conflict paths, the resource name, and the wire fields a rejection cites.

One collection, at the top level rather than under a week. A conflict is answered from a banner
that can be showing while the user is looking at any week, and the notice names a block rather than
a week, so nesting it under one would make the client hold a week it does not need in order to
resolve what it was shown.
"""

from __future__ import annotations

from typing import Final

from syncr_api.core.settings import API_PREFIX

# `/api/v1/conflicts`, built from the versioned prefix rather than written out.
CONFLICTS_PREFIX: Final = f"{API_PREFIX}/conflicts"

# Relative to the router's own prefix. Path parameters are snake_cased, as every other path
# parameter this api declares is.
CONFLICTS_PATH: Final = ""
RESOLVE_PATH: Final = "/{conflict_id}/resolve"

CONFLICT_RESOURCE: Final = "conflict"

# The query parameter the open list is read with, and the two body fields a rejection names, so a
# field error and the schema that declares the field cannot spell either two ways.
RESOLVED_PARAMETER: Final = "resolved"
RESOLUTION_FIELD: Final = "resolution"
ANCHOR_TYPE_FIELD: Final = "anchorTypeId"
