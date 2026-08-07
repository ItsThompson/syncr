"""The week, as a plan: the ledger ``syncr week show`` prints.

The heading, the four readings, the counts, the plan's currency, and then the day rows. The
verdict is placed between the summary and the days by the shared renderer, which is why this
view has a heading group and a body group rather than one list of lines.

Every figure comes from the api's ``readings``, never from counting the document here. The
strip's numbers and the budget report's numbers are the same numbers, and a client that
re-derived one would be a second arithmetic that can disagree.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from syncr_cli.rendering.day_rows import day_heading, day_sections
from syncr_cli.rendering.durations import hours_tenths
from syncr_cli.rendering.human import PROSE_WIDTH, iso_deadline
from syncr_domain.weeks import local_days
from syncr_domain.zones import resolve_zone

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_cli.wire.reading import JsonMapping
    from syncr_cli.wire.week import Readings, WeekView

# What separates the readings on one line. Wide enough that the eye reads four figures rather
# than one sentence.
GAP: Final = "    "

DATE_RANGE_SEPARATOR: Final = " - "


@dataclass(frozen=True, slots=True)
class WeekLedger:
    """One week's read, ready to print in either format.

    ``area_names`` is a separate read: a block carries the Area it is charged to as an
    identifier, and the ledger prints Areas by name because a column of identifiers is not a
    ledger. Keyed by the identifier as the wire spells it, so one map serves this surface and the
    backlog's. An Area the read did not name renders as no Area rather than as a raw identifier.
    """

    week: WeekView
    area_names: dict[str, str] = field(default_factory=dict)

    @property
    def payload(self) -> JsonMapping:
        return self.week.payload

    def header_lines(self) -> list[str]:
        lines = [self._heading()]
        if self.week.readings is None:
            lines.extend(["", *_wrapped(self.week.empty_statement or _NO_PLAN)])
            return lines
        lines.extend(["", *self._summary(self.week.readings)])
        return lines

    def body_lines(self) -> list[str]:
        if self.week.live is None:
            return []
        entries = self.week.live.entries(conflicted_block_ids=self.week.conflicted_block_ids)
        sections = day_sections(
            iso_week=self.week.iso_week,
            zone_by_date=self.week.zone_by_date,
            span=self.week.span,
            entries=entries,
            area_names=self.area_names,
        )
        return [line for section in sections for line in ["", *section.lines()]][1:]

    def render_deadline(self, moment: datetime) -> str:
        """An instant as a wall time in the zone the user is in on that date.

        Only for an instant inside this week, which is the zone map this read holds. A deadline
        beyond the week is printed as the instant itself rather than resolved against a zone this
        week cannot speak for.
        """
        for day in local_days(self.week.iso_week, self.week.zone_by_date, self.week.span):
            if day.interval.start <= moment < day.interval.end:
                local = moment.astimezone(resolve_zone(self.week.zone_by_date[day.on]))
                return f"{local:%a %H:%M}"
        return iso_deadline(moment)

    def _heading(self) -> str:
        """The week, the dates it covers, and the zones it is lived in."""
        return GAP.join(
            [str(self.week.iso_week), self._dates(), ", ".join(self.week.zones)]
        ).rstrip()

    def _dates(self) -> str:
        """``Mon 10 - Sun 16 February``, and both months or both years where they differ.

        A week that straddles a month names both, and one that straddles a new year names the
        years too: ``Mon 29 December 2025 - Sun 4 January 2026`` is otherwise a range a reader
        has to work out.
        """
        dates = self.week.iso_week.dates()
        first, last = dates[0], dates[-1]
        if first.year != last.year:
            return _range(
                f"{day_heading(first)} {first:%B %Y}", f"{day_heading(last)} {last:%B %Y}"
            )
        if first.month != last.month:
            return _range(f"{day_heading(first)} {first:%B}", f"{day_heading(last)} {last:%B}")
        return _range(day_heading(first), f"{day_heading(last)} {last:%B}")

    def _summary(self, readings: Readings) -> list[str]:
        """The four readings, then the counts and the plan's currency."""
        return [
            "  "
            + GAP.join(
                [
                    f"{readings.block_count} {_plural('block', readings.block_count)}",
                    f"{hours_tenths(readings.scheduled_minutes)} scheduled",
                    f"{hours_tenths(readings.discretionary_minutes)} discretionary",
                    f"{hours_tenths(readings.unallocated_minutes)} unallocated",
                ]
            ),
            "  "
            + GAP.join(
                [
                    f"{self.week.proposal_count} "
                    f"{_plural('proposal', self.week.proposal_count)} pending",
                    f"{readings.unconfirmed_days} "
                    f"{_plural('day', readings.unconfirmed_days)} unconfirmed",
                    f"plan: {readings.plan_currency}",
                ]
            ),
        ]


# What a week with no plan and no server statement says. The api composes the sentence in every
# case it knows, so this is the answer to a response that carried none rather than a second
# wording of a condition the server names.
_NO_PLAN: Final = "This week holds no plan."


def _plural(word: str, count: int) -> str:
    return word if count == 1 else f"{word}s"


def _wrapped(statement: str) -> list[str]:
    """The server's sentence, wrapped like every other sentence this CLI prints.

    Wrapped to a fixed width rather than to the terminal's, so the output a caller diffs between
    runs does not depend on the size of the window it was printed in.
    """
    return textwrap.wrap(statement, width=PROSE_WIDTH, initial_indent="  ", subsequent_indent="  ")


def _range(first: str, last: str) -> str:
    return f"{first}{DATE_RANGE_SEPARATOR}{last}"
