"""The ledger's day sections: which rows fall on which date, and how a row is spelled.

**A date's bounds are its own midnights, not a 24-hour slice.** A spring-forward date is 23
hours long and a date on a travel boundary can be 14, so the week's dates are resolved by the
domain's own day arithmetic rather than by dividing the span.

**A row appears once.** Consecutive dates can overlap when a mid-week move crosses far enough,
so a row is charged to the first date whose bounds hold its start. Charging it to both would
double a line in a ledger a reader is counting.

Every column is padded to a width computed from the rows being printed, which is what makes the
figures comparable by eye and what makes two reads of one week diff to nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syncr_cli.rendering.durations import duration_column_width, minutes_cell
from syncr_cli.wire.plan import NO_AREA, Entry
from syncr_domain.weeks import IsoWeek, local_days
from syncr_domain.zones import resolve_zone

if TYPE_CHECKING:
    from datetime import date
    from uuid import UUID

    from syncr_domain.intervals import Interval

# What a date with nothing on it says. A blank section would leave a reader wondering whether the
# date was omitted or empty.
NOTHING_PLANNED: Final = "nothing planned"

# How wide the title column is padded to, so the marker words line up down the page. A title
# longer than this pushes its own markers right rather than being truncated: a ledger that cut a
# title would hide the thing the row is about.
TITLE_COLUMN_LIMIT: Final = 34

SECTION_INDENT: Final = "  "
ROW_INDENT: Final = "   "
# What separates one column from the next, and one marker from the next. Two spaces, so a word in
# the marker column is never mistaken for part of the title beside it.
COLUMN_SEPARATOR: Final = "  "


@dataclass(frozen=True, slots=True)
class DaySection:
    """One date of the week: its heading, and the rows that fall on it."""

    heading: str
    rows: tuple[str, ...]

    def lines(self) -> list[str]:
        return [f"{SECTION_INDENT}{self.heading}", *self.rows]


@dataclass(frozen=True, slots=True)
class Layout:
    """The column widths one render uses, computed from the rows it is about to print."""

    duration: int
    area: int
    title: int

    @classmethod
    def of(cls, entries: tuple[Entry, ...], area_names: dict[UUID, str]) -> Layout:
        areas = [area_cell(entry, area_names) for entry in entries]
        return cls(
            duration=duration_column_width([entry.minutes for entry in entries]),
            area=max((len(cell) for cell in areas), default=len(NO_AREA)),
            title=min(TITLE_COLUMN_LIMIT, max((len(entry.title) for entry in entries), default=0)),
        )


def day_sections(
    *,
    iso_week: IsoWeek,
    zone_by_date: dict[date, str],
    span: Interval,
    entries: tuple[Entry, ...],
    area_names: dict[UUID, str],
) -> tuple[DaySection, ...]:
    """Every date of the week, in order, with its rows already spelled."""
    layout = Layout.of(entries, area_names)
    remaining = set(range(len(entries)))
    sections = []
    for day in local_days(iso_week, zone_by_date, span):
        # Indices rather than the entries themselves: two rows of one week can be equal in every
        # member the ledger prints, and removing "the equal one" would drop a real row.
        on_this_day = sorted(
            index
            for index in remaining
            if day.interval.start <= entries[index].start < day.interval.end
        )
        remaining.difference_update(on_this_day)
        sections.append(
            DaySection(
                heading=day_heading(day.on),
                rows=_rows(
                    [entries[index] for index in on_this_day],
                    zone=zone_by_date[day.on],
                    layout=layout,
                    area_names=area_names,
                ),
            )
        )
    return tuple(sections)


def day_heading(on: date) -> str:
    """A date as the ledger heads its section: ``Tue 11``."""
    return f"{on:%a %d}"


def area_cell(entry: Entry, area_names: dict[UUID, str]) -> str:
    """The Area column for one row.

    An Area this read did not name renders as no Area, which is the honest answer: the ledger
    cannot state a name it does not have, and the row is still readable without one.
    """
    if entry.area_id is None:
        return NO_AREA
    return area_names.get(entry.area_id, NO_AREA)


def _rows(
    entries: list[Entry], *, zone: str, layout: Layout, area_names: dict[UUID, str]
) -> tuple[str, ...]:
    if not entries:
        return (f"{ROW_INDENT}{NOTHING_PLANNED}",)
    return tuple(_row(entry, zone=zone, layout=layout, area_names=area_names) for entry in entries)


def _row(entry: Entry, *, zone: str, layout: Layout, area_names: dict[UUID, str]) -> str:
    """One row: the wall times, the duration, the Area, the title, then the words.

    The gap after the wall times is one space rather than two, because the duration is right-aligned
    in its own column: a three-digit value takes the whole column and a two-digit one leaves the
    second space itself, which is what puts the ``m`` of every duration under the one above it.
    """
    row = (
        f"{ROW_INDENT}{_wall_times(entry, zone)} "
        f"{minutes_cell(entry.minutes, layout.duration)}{COLUMN_SEPARATOR}"
        f"{area_cell(entry, area_names).ljust(layout.area)}{COLUMN_SEPARATOR}"
        f"{entry.title.ljust(layout.title)}"
    )
    if entry.markers:
        row = f"{row}{COLUMN_SEPARATOR}{COLUMN_SEPARATOR.join(entry.markers)}"
    return row.rstrip()


def _wall_times(entry: Entry, zone: str) -> str:
    """A row's span as wall clock times in the zone the user is in that day.

    Both ends in one zone, so a block that crosses a date boundary reads ``23:00-07:00`` rather
    than being split across two sections: it is one thing that happens, on the date it began.
    """
    resolved = resolve_zone(zone)
    start = entry.interval.start.astimezone(resolved)
    end = entry.interval.end.astimezone(resolved)
    return f"{start:%H:%M}-{end:%H:%M}"
