"""The vocabularies, bounds, table names, and route paths of the anchor subsystem.

Two closed sets carry the design of this package.

``post_scope`` says what a recovery window forbids, and it has three members rather than two
because an empty list cannot express the difference between "forbids nothing" and "forbids
everything". ``areas`` names the Areas that may not be scheduled there and everything else
still may; ``all`` forbids every Area, which is what a long flight or a general anaesthetic
is; ``none`` generates no window at all. The list is non-empty for exactly one of the three,
which is a biconditional the schema states as a check constraint.

``AnchorTypeSource`` says where an anchor's type came from. A rule match and a user override
are the same column value with different authority: an override survives a rule change and a
match does not, so the interface has to be able to tell them apart.

The minute bounds are ceilings on publisher-independent, user-authored values, and each has a
different reason. A LEAD is bounded at a week because the week assembler widens its anchor
read by the largest lead any type declares, so an unbounded lead is an unbounded
read. A DURATION is bounded at a day because a buffer longer than a day is a period the user
should be declaring off-plan rather than as an anchor's shadow. The largest lead any settled
record uses is 14 hours, so both bounds have a wide margin over the real values.

The text bounds are the other kind: every one of them is a publisher-controlled value that
reaches a column with a width. They are enforced where a feed's event becomes an anchor row,
in :mod:`syncr_api.anchors.identity`, because a `VARCHAR` that raises at flush turns one
oversized SUMMARY into a whole feed's sync failing.
"""

from __future__ import annotations

from typing import Final, Literal

from syncr_api.core.settings import API_PREFIX

ANCHORS_TABLE: Final = "anchors"
ANCHOR_TYPES_TABLE: Final = "anchor_types"

# Built from the versioned prefix rather than written out, so a change to the prefix
# reaches this module.
ANCHORS_PREFIX: Final = f"{API_PREFIX}/anchors"
ANCHOR_TYPES_PREFIX: Final = f"{API_PREFIX}/anchor-types"
# Relative to each router's prefix.
ANCHOR_TYPE_ASSIGNMENT_PATH: Final = "/{anchor_id}/type"
ANCHOR_TYPE_PATH: Final = "/{anchor_type_id}"
# Declared BEFORE `ANCHOR_TYPE_PATH` on the router, because the framework matches in
# declaration order and `/order` would otherwise be read as an identifier.
ANCHOR_TYPE_ORDER_PATH: Final = "/order"

ANCHOR_RESOURCE: Final = "anchor"
ANCHOR_TYPE_RESOURCE: Final = "anchor type"

# What a recovery window forbids. See the module docstring for why there are three.
type PostScope = Literal["none", "all", "areas"]
FORBIDS_NOTHING: Final[PostScope] = "none"
FORBIDS_EVERYTHING: Final[PostScope] = "all"
FORBIDS_AREAS: Final[PostScope] = "areas"
POST_SCOPES: Final = (FORBIDS_NOTHING, FORBIDS_EVERYTHING, FORBIDS_AREAS)

# The user-facing form of the scope control, so the three-way choice reads as a choice
# rather than as a list that happens to be empty.
POST_SCOPE_LABEL: Final = "forbids after"
POST_SCOPE_LABELS: Final[dict[PostScope, str]] = {
    FORBIDS_NOTHING: "nothing",
    FORBIDS_EVERYTHING: "everything",
    FORBIDS_AREAS: "these Areas",
}

# Where an anchor's type came from, which decides whether a rule may replace it.
type AnchorTypeSource = Literal["unmatched", "rule", "override"]
UNMATCHED: Final[AnchorTypeSource] = "unmatched"
RULE_MATCH: Final[AnchorTypeSource] = "rule"
USER_OVERRIDE: Final[AnchorTypeSource] = "override"
ANCHOR_TYPE_SOURCES: Final = (UNMATCHED, RULE_MATCH, USER_OVERRIDE)

# What an anchor is in syncr, stated on the detail payload rather than left for a reader to
# infer from the absence of an edit route.
READ_ONLY_STATEMENT: Final = (
    "This commitment is read-only in syncr. It is a fact imported from {source}, and the "
    "source of truth stays there: edit or remove it in {source} and the next sync follows. "
    "Its type is the one thing you can change here, and that changes what it reserves around "
    "itself rather than the commitment itself."
)

# Column widths for the values a PUBLISHER chooses the length of. A feed body is capped at
# 8 MiB and nothing inside it bounds one property, so each of these is a magnitude a feed can
# make arbitrarily large.
#
# A UID is generous because it is an identity rather than a label: the occurrence form is a
# series UID plus a 16-character wall-time suffix, and a publisher that emits a long UID has
# not done anything wrong. Past the bound it is digested rather than cut, per `identity.py`.
EXTERNAL_UID_MAX_LENGTH: Final = 512
# A title is a label, read in a grid block and a ledger row, both of which are tight. Past the
# bound it is cut, and matching reads the STORED title, so a substring past this point does
# not match. That is a stated consequence of bounding it rather than an oversight: no real
# SUMMARY is near it.
ANCHOR_TITLE_MAX_LENGTH: Final = 500
# Stored with no reader at all, so this bound only has to stop a column from overflowing.
ANCHOR_LOCATION_MAX_LENGTH: Final = 500

# Column widths for the values the USER authors. A name is read in a rules table and on an
# anchor, both narrow; a match substring is compared against a bounded title, so a substring
# longer than the title it is matched against could never match.
ANCHOR_TYPE_NAME_MAX_LENGTH: Final = 60
MATCH_TITLE_MAX_LENGTH: Final = 200

# Minutes. See the module docstring for why a lead and a duration are bounded differently.
LEAD_MINUTES_MAX: Final = 7 * 24 * 60
DURATION_MINUTES_MAX: Final = 24 * 60
MINUTES_MIN: Final = 0

# How many types one tenant may declare, and how many Areas one recovery window may name.
# Both are hand-authored lists, so both bounds are far above what a person writes; what they
# stop is a request body arriving with a million members before anything validates it.
ANCHOR_TYPES_MAX: Final = 100
FORBIDDEN_AREAS_MAX: Final = 100

# The span one anchor read may cover, and how many rows one page holds. The span is bounded
# because a read of "every anchor ever" is not a question the interface asks: the week view
# reads a week, and the Settings panel reads a horizon. The page is bounded because a feed may
# legitimately contribute thousands of anchors inside a year. Neither bounds the week assembly's
# own read, which is bounded by its week plus the reach the two minute bounds above cap.
ANCHOR_SPAN_DAYS_MAX: Final = 366
ANCHOR_PAGE_LIMIT_DEFAULT: Final = 200
ANCHOR_PAGE_LIMIT_MAX: Final = 500
