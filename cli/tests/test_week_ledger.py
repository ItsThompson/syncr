"""The ledger ``week show`` prints, against the shape the specification documents.

The week under test is the one in section 17's example: the same dates, the same six rows on the
same Tuesday, the same words in the marker column. So the assertions are against a documented
shape rather than against whatever this renderer happened to produce.

Three properties matter beyond the layout. Conflicts, pins, and origins are named in words, because
a pipe strips color and does not strip a word. A forbidden window is printed so the gap is
explained, and it is visibly not a block because it has no Area. And two reads of one week produce
the same bytes, so an agent can diff two invocations.
"""

from __future__ import annotations

from typing import Any

import pytest

from syncr_cli.rendering.human import render_human
from syncr_cli.rendering.ledger import WeekLedger
from syncr_cli.results import CliResult
from syncr_cli.wire.plan import CONFLICT_MARKER, FORBIDDEN_MARKER, NO_AREA, PINNED_MARKER
from syncr_cli.wire.week import WeekView
from tests import payloads

TUESDAY = "2026-02-10"

AREA_NAMES = {
    str(payloads.FITNESS_ID): "Fitness",
    str(payloads.CAREER_ID): "Career",
    str(payloads.TRANSIT_ID): "Transit",
}


def documented_week(*, week_verdict: dict[str, Any] | None = None) -> WeekView:
    """Section 17's example week: six rows on one Tuesday, one of them a forbidden window."""
    blocks = [
        payloads.block(
            identifier="gym",
            start=f"{TUESDAY}T05:30:00+00:00",
            end=f"{TUESDAY}T06:30:00+00:00",
            title="Gym · Shoulder & Arms",
            origin="habit",
            area_id=payloads.FITNESS_ID,
            pinned=True,
        ),
        payloads.block(
            identifier="leetcode",
            start=f"{TUESDAY}T07:00:00+00:00",
            end=f"{TUESDAY}T09:30:00+00:00",
            title="Leetcode · Graphs",
        ),
        payloads.block(
            identifier="prep",
            start=f"{TUESDAY}T10:00:00+00:00",
            end=f"{TUESDAY}T10:30:00+00:00",
            title="Prep for Kontron Interview",
            origin="prep",
        ),
        payloads.block(
            identifier="transit",
            start=f"{TUESDAY}T15:00:00+00:00",
            end=f"{TUESDAY}T15:30:00+00:00",
            title="Leave for Uni",
            origin="transit",
            area_id=payloads.TRANSIT_ID,
        ),
        payloads.block(
            identifier="interview",
            start=f"{TUESDAY}T16:00:00+00:00",
            end=f"{TUESDAY}T16:45:00+00:00",
            title="Kontron Placement Interview",
            origin="anchor",
            area_id=None,
        ),
    ]
    windows = [
        payloads.forbidden_window(
            start=f"{TUESDAY}T16:45:00+00:00",
            end=f"{TUESDAY}T18:00:00+00:00",
            label="recovery · Kontron Interview",
        )
    ]
    return WeekView.read(
        payloads.week(
            live=payloads.plan_document(blocks=blocks, windows=windows),
            week_verdict=week_verdict,
            conflicts=[{"blockId": "interview"}],
        )
    )


def rendered(view: WeekView) -> str:
    """The ledger as the command renders it: the same result object, verdict and all."""
    return render_human(
        CliResult.succeeded(
            WeekLedger(week=view, area_names=AREA_NAMES),
            verdict=view.verdict,
            operation=view.operation,
        )
    )


def test_the_heading_names_the_week_its_dates_and_its_zone() -> None:
    assert rendered(documented_week()).splitlines()[0] == (
        "2026-W07    Mon 09 - Sun 15 February    Europe/London"
    )


def test_the_strip_holds_the_four_readings_then_the_counts_and_the_currency() -> None:
    lines = rendered(documented_week()).splitlines()

    assert lines[2] == (
        "  91 blocks    80.8h scheduled    52.1h discretionary    18.4h unallocated"
    )
    assert lines[3] == "  0 proposals pending    3 days unconfirmed    plan: current"


def test_a_pending_proposal_is_counted() -> None:
    view = WeekView.read(payloads.week(proposal={"changes": []}))

    assert "1 proposal pending" in rendered(view)


def test_the_day_rows_are_the_six_the_specification_shows() -> None:
    rows = _rows_under(rendered(documented_week()), "Tue 10")

    assert rows == [
        "   05:30-06:30  60m  Fitness  Gym · Shoulder & Arms         pinned",
        "   07:00-09:30 150m  Career   Leetcode · Graphs",
        "   10:00-10:30  30m  Career   Prep for Kontron Interview    prep",
        "   15:00-15:30  30m  Transit  Leave for Uni                 transit",
        "   16:00-16:45  45m  --       Kontron Placement Interview   anchor  CONFLICT",
        "   16:45-18:00  75m  --       recovery · Kontron Interview  forbidden",
    ]


def test_the_durations_are_right_aligned_so_they_compare_by_eye() -> None:
    rows = _rows_under(rendered(documented_week()), "Tue 10")
    columns = {row.index("m", 14) for row in rows}

    assert len(columns) == 1
    assert " 60m" in rows[0]
    assert "150m" in rows[1]


@pytest.mark.parametrize(
    "word", [PINNED_MARKER, CONFLICT_MARKER, FORBIDDEN_MARKER, "prep", "transit", "anchor"]
)
def test_every_state_is_named_in_a_word_rather_than_in_color(word: str) -> None:
    # A pipe strips color. A pipe does not strip a word.
    output = rendered(documented_week())

    assert word in output
    assert "\x1b[" not in output


def test_a_forbidden_window_is_printed_and_carries_no_area() -> None:
    # It is printed so the gap is explained, and it is visibly not a block because it has no Area.
    row = next(
        line for line in rendered(documented_week()).splitlines() if FORBIDDEN_MARKER in line
    )

    assert NO_AREA in row
    assert "recovery · Kontron Interview" in row


def test_a_day_with_nothing_on_it_says_so_rather_than_being_omitted() -> None:
    output = rendered(documented_week())

    assert "nothing planned" in output
    for day in ("Mon 09", "Tue 10", "Wed 11", "Thu 12", "Fri 13", "Sat 14", "Sun 15"):
        assert f"  {day}" in output


def test_two_reads_of_one_week_produce_the_same_bytes() -> None:
    # Output stable enough to diff between runs is what lets an agent compare two invocations.
    assert rendered(documented_week()) == rendered(documented_week())


def test_the_verdict_sits_between_the_summary_and_the_days_with_its_provenance() -> None:
    output = rendered(documented_week(week_verdict=payloads.verdict()))
    lines = output.splitlines()
    verdict_line = next(index for index, line in enumerate(lines) if "cannot hold" in line)
    tuesday = next(index for index, line in enumerate(lines) if line == "  Tue 10")

    assert lines[verdict_line].endswith("[capacity check]")
    assert verdict_line < tuesday
    assert "1h20m short on Career before Fri 09:00" in _prose(output)
    assert "after honoring the Fitness floor of 5h" in _prose(output)
    assert "4 tradeoffs. Nothing is chosen for you." in _prose(output)


def test_a_solved_verdict_says_where_it_came_from_too() -> None:
    output = rendered(
        documented_week(week_verdict=payloads.verdict(provenance="solver", shortfalls=[]))
    )

    assert "[after solving]" in output
    assert "This week cannot hold its commitments" in output


def test_a_capacity_check_that_found_nothing_does_not_claim_the_week_works() -> None:
    # Capacity arithmetic finding nothing means it could not prove the week impossible, which is a
    # weaker statement than the week being possible.
    output = rendered(documented_week(week_verdict=payloads.verdict(shortfalls=[])))

    assert "Capacity is sufficient" in output
    assert "holds its commitments" not in output


def test_a_week_with_no_plan_prints_the_servers_own_sentence() -> None:
    # The api composes the sentence in every case it knows, so the ledger prints the server's
    # statement rather than inventing a second wording. Long ones wrap like every other sentence.
    statement = (
        "2026-W07 has no plan, because syncr still needs at least one Area and a day shape for "
        "each weekday. Declare what is missing and this week is planned without you asking again."
    )
    view = WeekView.read(payloads.empty_week(statement=statement))

    output = rendered(view)

    assert statement in _prose(output)
    assert max(len(line) for line in output.splitlines()) <= 80
    assert "nothing planned" not in output


def test_a_deadline_beyond_the_week_is_printed_as_the_instant_itself() -> None:
    # Naming `Fri 09:00` needs the zone the user is in on that date, and this week cannot speak for
    # a date outside itself.
    beyond = payloads.verdict(shortfalls=[payloads.shortfall(deadline="2026-03-20T09:00:00+00:00")])

    assert "2026-03-20T09:00:00+00:00" in rendered(documented_week(week_verdict=beyond))


def test_a_block_that_crosses_midnight_is_charged_to_the_day_it_began() -> None:
    # One thing that happens, on the date it began, read as 23:00-07:00 rather than split in two.
    view = WeekView.read(
        payloads.week(
            live=payloads.plan_document(
                blocks=[
                    payloads.block(
                        identifier="sleep",
                        start=f"{TUESDAY}T23:00:00+00:00",
                        end="2026-02-11T07:00:00+00:00",
                        title="Sleep",
                        origin="frame",
                        area_id=None,
                    )
                ]
            )
        )
    )

    assert "   23:00-07:00 480m" in rendered(view)
    assert _rows_under(rendered(view), "Wed 11") == ["   nothing planned"]


def _prose(output: str) -> str:
    """The output with its wrapping collapsed, for asserting a sentence that spans two lines."""
    return " ".join(output.split())


def _rows_under(output: str, heading: str) -> list[str]:
    lines = output.splitlines()
    start = lines.index(f"  {heading}") + 1
    rows = []
    for line in lines[start:]:
        if not line.strip():
            break
        rows.append(line)
    return rows
