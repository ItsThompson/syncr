"""The vocabularies, bounds, table name, and route paths of the calendar subsystem.

Two closed sets carry the whole design of this package. ``provider`` says which adapter
reads a source, and ``role`` says which direction it points: many sources are read as
anchors, exactly one is written to as a projection. Both are ``Literal`` types as well as
tuples, so a writer's signature names the members and the database's check constraint is
generated from the same definition.

``horizon_days`` belongs to the write target alone. An anchor source has no horizon
because it is read over whatever span the assembler asks for, and the projection has one
because a destructive reconciliation needs a bound past which it will not delete.

A rejection kind is closed for the same reason a role is: the Settings panel groups
rejected events by class and states a reason per class, so a new class is a deliberate
edit here and in the message that renders it, rather than a free-text string that reaches
the user.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final, Literal

from syncr_api.core.settings import API_PREFIX

CALENDAR_SOURCES_TABLE: Final = "calendar_sources"

# `/api/v1/calendar-sources`, built from the versioned prefix rather than written out.
CALENDAR_SOURCES_PREFIX: Final = f"{API_PREFIX}/calendar-sources"
# Relative to the router's prefix.
SOURCE_PATH: Final = "/{source_id}"
SOURCE_SYNC_PATH: Final = "/{source_id}/sync"
SOURCE_ROLE_PATH: Final = "/{source_id}/role"
SOURCE_HORIZON_PATH: Final = "/{source_id}/horizon"
SOURCE_REMOTE_CALENDARS_PATH: Final = "/{source_id}/remote-calendars"

SOURCE_RESOURCE: Final = "calendar source"

# What a Google rejection names as the thing that failed. ICS reports the component's own name
# (`VEVENT`); an API answers items, so the panel says what one is in the provider's own terms.
GOOGLE_COMPONENT: Final = "event"

# What a rejection's line is when the provider states none. ICS attributes a rejection to the line
# the component began on; an API answers JSON, where there is no line for a reader to look at.
UNKNOWN_LINE: Final = 0

type CalendarProvider = Literal["google", "ics"]
GOOGLE: Final[CalendarProvider] = "google"
ICS: Final[CalendarProvider] = "ics"
CALENDAR_PROVIDERS: Final = (GOOGLE, ICS)

type CalendarRole = Literal["anchor-source", "write-target"]
ANCHOR_SOURCE: Final[CalendarRole] = "anchor-source"
WRITE_TARGET: Final[CalendarRole] = "write-target"
CALENDAR_ROLES: Final = (ANCHOR_SOURCE, WRITE_TARGET)

# What a source's panel reports, and the reason the read model carries a state rather than
# a pair of booleans. An excluded source is NOT an error: it reports zero anchors because
# the user asked it to, and rendering that as a failure would tell them something broke.
type SourceState = Literal["never-synced", "excluded", "error", "ok"]
NEVER_SYNCED: Final[SourceState] = "never-synced"
EXCLUDED: Final[SourceState] = "excluded"
ERROR: Final[SourceState] = "error"
OK: Final[SourceState] = "ok"
SOURCE_STATES: Final = (NEVER_SYNCED, EXCLUDED, ERROR, OK)

# Why one component of a feed produced no event. Each member is a row of the ICS ingest table,
# and the panel states a message per member.
#
# A duplicate UID is deliberately absent, and there is no tuple of these: a duplicate is RESOLVED
# rather than rejected, so it is counted on the outcome instead, and the column that holds a
# rejection is JSONB with no check constraint for a tuple to generate. A member nothing can emit
# would be a state the panel has copy for and never renders.
type RejectionKind = Literal[
    "missing-duration",
    "unknown-zone",
    "malformed-value",
    "unparseable-recurrence",
    "read-budget-spent",
]
MISSING_DURATION: Final[RejectionKind] = "missing-duration"
UNKNOWN_ZONE: Final[RejectionKind] = "unknown-zone"
MALFORMED_VALUE: Final[RejectionKind] = "malformed-value"
UNPARSEABLE_RECURRENCE: Final[RejectionKind] = "unparseable-recurrence"
# Not a fault in the component at all: the feed ran out of the time syncr will spend reading it
# before reaching this one. It needs its own class because the panel groups by class and states a
# reason per class, and a feed of ordinary meetings cut short read as a recurrence problem it did
# not have. What the user does about it also differs: every other class is the publisher's to fix.
READ_BUDGET_SPENT: Final[RejectionKind] = "read-budget-spent"

# The projection horizon, in days. Fourteen is the stated default. The floor is one day
# because a zero-day horizon would project nothing while reading as configured, and the
# ceiling is a quarter, past which a destructive reconciliation writes hundreds of events
# a solve will revise before they arrive.
HORIZON_DAYS_DEFAULT: Final = 14
HORIZON_DAYS_MIN: Final = 1
HORIZON_DAYS_MAX: Final = 90

# Column widths. A feed URL is bounded well above what a publisher emits; a display name
# is what the user types; the cursor holds an ETag or an HTTP-date, both far shorter.
DISPLAY_NAME_MAX_LENGTH: Final = 200
EXTERNAL_ID_MAX_LENGTH: Final = 2_048
CURSOR_MAX_LENGTH: Final = 512
LAST_ERROR_MAX_LENGTH: Final = 500

# How much of one rejection's detail is KEPT. Every detail is written to JSONB on the sync state and
# served whole by the read route, and several of them quote a value the FEED chose the length of: a
# rule dateutil refused, or a converter's own complaint about a literal. A publisher can make any of
# those megabytes wide. Bounding the detail where it is built is the net; the messages that name a
# value's SIZE instead of quoting it are the attribution, and both are wanted.
#
# Not a maximum for the whole string: a truncated detail also states the full length, so the stored
# value is this many characters plus that short suffix. Naming the length is the point, since a
# reader has to be able to tell a long value from a truncated explanation.
DETAIL_MAX_LENGTH: Final = 300

# How many entries of ONE rejection kind are kept. The panel groups by kind and states a reason per
# kind, so what a reader acts on is the class plus a few instances of it, and the instances past
# those are the same explanation with a different line number. Five kinds times three is a stored
# payload of at most fifteen entries, each already bounded by DETAIL_MAX_LENGTH.
#
# The COUNT of rejections is carried separately and this does not bound it. A feed that refuses
# 50,000 components stores fifteen of them and a total of 50,000: a term that stopped closing
# against the components the feed offered would lose occupancy with no explanation anywhere.
REJECTIONS_KEPT_PER_KIND: Final = 3

# How long a feed read may take, and how much of one is read. A publisher that stalls must
# not hold a worker tick open, and a feed that streams forever must not exhaust memory: both
# become a stated `last_error` with the anchors retained.
FETCH_TIMEOUT_SECONDS: Final = 15.0
MAX_FEED_BYTES: Final = 8 * 1024 * 1024

# How often the worker polls a feed. Feeds are polled on a schedule rather than on demand,
# and an ICS publisher's own refresh is measured in hours, so a quarter hour is already
# finer than the data changes.
SYNC_INTERVAL: Final = timedelta(minutes=15)

# How long a feed may go on failing before it is worth telling the user about. Long enough that one
# missed poll of the interval above is not a notice, short enough that a reader planning tomorrow
# morning is told today.
#
# THE SERVER OWNS THIS FIGURE AND IT DOES NOT REACH THE WIRE. Three surfaces want to apply it: the
# Settings panel, the day a reader is looking at, and the week grid. A threshold on the wire lets
# each of them decide staleness for itself, which is three answers to one question and two of them
# free to drift. `calendars/feed_notices.py` applies it once and names what it decided.
STALE_AFTER: Final = timedelta(hours=12)

# How many days one event may span. A multi-year all-day event is legitimate, so this is not the
# projection horizon; a century is past anything a calendar publishes and well inside what date
# arithmetic can represent from any year a feed can name.
#
# The bound exists because a magnitude is not a syntax error: `DTEND;VALUE=DATE:99991231` parses
# perfectly and then overflows the arithmetic that would place it. Rejecting it where the magnitude
# is READ is what lets the rejection name the property, rather than surfacing as a fault with no
# component and no line.
MAX_EVENT_DAYS: Final = 36_600

# How many events one feed may contribute. A recurrence with no UNTIL and no COUNT expands
# for as long as the horizon allows, and a hostile or mistaken feed can hold thousands of
# such rules, so expansion is bounded rather than trusted.
MAX_EVENTS_PER_FEED: Final = 10_000

# How long one feed's whole parse may take. FETCH_TIMEOUT_SECONDS bounds the network half of a read
# for exactly this reason; this is the other half, and it was missing.
#
# Nothing bounds a feed's COMPONENT COUNT, so the per-series step bound multiplies by however many
# components 8 MiB holds. Measured: a rule that yields nothing but forces dateutil to scan to its
# maximum year costs 2.5 seconds and one step, and 8 MiB of that shape is upwards of 36 hours of one
# worker tick with its transaction open, reporting no events and no rejections. A feed of legitimate
# shape can reach tens of minutes the same way.
#
# A bound syncr owns cannot interrupt a call it is inside, so this is checked BETWEEN components:
# one pathological component is tolerated, a feed made of them is not.
#
# The value has headroom over the slowest LEGITIMATE feed measurable, which is 9,800 events from
# 700 daily series running since 2010, at 6.9 to 7.9 seconds across runs and machines. Thirty
# seconds was the first choice and described as "more than four times" that, which was wrong: it is
# under four times the slower measurement. The cost of cutting a real feed short is occupancy
# missing from a plan while the source still reads as healthy, so the multiple is worth more than
# the seconds saved on a feed nobody should be publishing.
MAX_PARSE_SECONDS: Final = 60.0

# How long ONE recurrence expansion may run before the parent stops waiting for it.
# MAX_PARSE_SECONDS above can only be checked between components; one component whose rule is
# legal but never satisfiable (``FREQ=SECONDLY;BYMONTH=2;BYMONTHDAY=30;BYHOUR=2``) walks inside a
# single dateutil call measured at 1,290 seconds. That expansion runs in its own process, so the
# parent CAN bound it: a wait past this deadline terminates the worker and answers a rejection.
#
# The value has two-sided headroom. The slowest legitimate single expansion measurable is under a
# second (a weekly rule reaching dateutil's maximum year costs 0.54s), and even the step-bounded
# runaway of 50,000 secondly steps completes well inside it. The cheapest known hang of the
# unsatisfiable family costs upwards of 200 seconds, twenty times this figure. A deadline below
# ten would risk cutting a legitimate expansion on a loaded machine for no time saved that
# matters; one above it leaves a hung reader holding a worker tick for minutes.
EXPANSION_DEADLINE_SECONDS: Final = 10.0

# How many recurrence-expansion processes are kept to take work from. One suffices for the
# worker, which reads one tenant's feeds sequentially and one tenant at a time; the second lets
# an on-demand read on the api proceed while a worker tick holds the first. A process idles at
# roughly zero cost between feeds, so spare capacity here is cheaper than serializing readers.
EXPANSION_POOL_SIZE: Final = 2
