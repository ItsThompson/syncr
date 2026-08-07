"""What ``plan show --date`` and ``day confirm`` answer with: one date's ledger, in both renderings.

One view for both, because both answer with the same resource. Confirming a day reads the settled
ledger back, so the difference a reader sees is the lead line saying what just happened, not a
second layout for one thing.

**Every figure comes from the server.** The block count, how many are presumed, and how many days
are unconfirmed are all computed there, so this surface and the Week screen's strip cannot disagree
about the same figure.

**A row with nothing recorded reads as presumed.** That is the ordinary case rather than a gap: a
block is presumed complete unless the user says otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syncr_cli.rendering.durations import duration_column_width, minutes_cell
from syncr_cli.rendering.views import PlainView
from syncr_domain.zones import resolve_zone

if TYPE_CHECKING:
    from zoneinfo import ZoneInfo

    from syncr_cli.wire.day import DayLedger, LedgerRow
    from syncr_cli.wire.reading import JsonMapping

GAP: Final = "    "
ROW_INDENT: Final = "   "
COLUMN_SEPARATOR: Final = "  "

TITLE_COLUMN_LIMIT: Final = 34

# What a date with nothing on it says. A blank body would leave a reader wondering whether the date
# was omitted or empty.
NOTHING_PLANNED: Final = "nothing planned"

# What the header says about a day nobody has answered for, and about one that is settled.
UNCONFIRMED: Final = "unconfirmed"
CONFIRMED: Final = "confirmed"

# The word a row carries when the block has not ended yet, so the two sections the api sends are
# still distinguishable in one column layout.
AHEAD_MARKER: Final = "ahead"


@dataclass(frozen=True, slots=True)
class DayLedgerView(PlainView):
    """One date, as a ledger: the heading, the counts, then the rows in time order."""

    day: DayLedger
    lead: str | None = None

    @property
    def payload(self) -> JsonMapping:
        return self.day.payload

    def header_lines(self) -> list[str]:
        heading = GAP.join([f"{self.day.on:%a %d %B %Y}", self.day.zone])
        lines = [heading] if self.lead is None else [f"{self.lead}  {heading}"]
        lines.extend(["", "  " + GAP.join(self._counts())])
        return lines

    def body_lines(self) -> list[str]:
        rows = self.day.rows
        if not rows:
            return [f"{ROW_INDENT}{NOTHING_PLANNED}"]
        width = duration_column_width([row.duration_minutes for row in rows])
        areas = max(len(row.area_name) for row in rows)
        titles = min(TITLE_COLUMN_LIMIT, max(len(row.title) for row in rows))
        ahead = {row.block_id for row in self.day.ahead}
        # Resolved once per ledger rather than once per row: it is one zone for the whole day, and a
        # lookup per row is a lookup per row.
        zone = resolve_zone(self.day.zone)
        return [
            self._row(
                row,
                width=width,
                areas=areas,
                titles=titles,
                ahead=row.block_id in ahead,
                zone=zone,
            )
            for row in rows
        ]

    def _counts(self) -> list[str]:
        return [
            f"{self.day.block_count} {_plural('block', self.day.block_count)}",
            f"{self.day.presumed_count} presumed",
            CONFIRMED if self.day.confirmed_at is not None else UNCONFIRMED,
            f"{self.day.unconfirmed_days} {_plural('day', self.day.unconfirmed_days)} unconfirmed",
        ]

    def _row(
        self,
        row: LedgerRow,
        *,
        width: int,
        areas: int,
        titles: int,
        ahead: bool,
        zone: ZoneInfo,
    ) -> str:
        """One row: the wall times, the duration, the Area, the title, then the words."""
        line = (
            f"{ROW_INDENT}{_wall_times(row, zone)} "
            f"{minutes_cell(row.duration_minutes, width)}{COLUMN_SEPARATOR}"
            f"{row.area_name.ljust(areas)}{COLUMN_SEPARATOR}"
            f"{row.title.ljust(titles)}"
        )
        for marker in _markers(row, ahead=ahead):
            line = f"{line}{COLUMN_SEPARATOR}{marker}"
        return line.rstrip()


def _wall_times(row: LedgerRow, zone: ZoneInfo) -> str:
    """A row's span as wall clock times in the zone the day's bounds were resolved in."""
    start = row.interval.start.astimezone(zone)
    end = row.interval.end.astimezone(zone)
    return f"{start:%H:%M}-{end:%H:%M}"


def _markers(row: LedgerRow, *, ahead: bool) -> list[str]:
    """The words a row carries: its origin, what the log says, and whether it has ended.

    Words, not color: a pipe strips color and a pipe does not strip a word.
    """
    markers = [row.origin, row.outcome_statement]
    if ahead:
        markers.append(AHEAD_MARKER)
    return markers


def _plural(word: str, count: int) -> str:
    return word if count == 1 else f"{word}s"
