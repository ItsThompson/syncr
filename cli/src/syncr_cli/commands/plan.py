"""``plan show``, ``plan solve``, and ``plan approve``.

Three commands, and the middle one is the only place in this CLI that follows long-running work.

**SSE is out of scope by design, so an operation is polled.** The ``Operation`` resource was built
to be pollable for exactly this reason, and a streaming client here would be a second delivery
mechanism for one contract. The poll is capped and backs off, so a tight loop on a long solve does
not hammer the API.

**A wait ends by the operation's terminal status, and three of the four endings are not failures.**
``succeeded`` exits 0 and prints the resulting plan summary and verdict, ``superseded`` exits 9 and
names the operation that displaced it so an agent follows the chain rather than adding another to
it, ``failed`` exits 1 with the cause the server stated, and a timeout exits 10 and carries the
operation so the wait is resumable rather than lost.

**An approval demands an idempotency key and this command always sends one.** Approval appends to a
table with no update and no delete path and there is no unapprove, so a retry without a key would
append a second approved revision of one document. Exiting 6 is what a cleared slot answers with,
which the api's own conflict says.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from syncr_cli.arguments import stated_date
from syncr_cli.commands.week import read_week
from syncr_cli.errors import WaitTimedOut
from syncr_cli.operations import wait_for_operation
from syncr_cli.parser import add_verb, register_command
from syncr_cli.rendering.day_views import DayLedgerView
from syncr_cli.rendering.edit_views import WeekApprovedView
from syncr_cli.rendering.solve_views import SolveRequestedView, SolveSettledView
from syncr_cli.results import CliResult
from syncr_cli.wire.approval import WeekApproved
from syncr_cli.wire.day import DayLedger
from syncr_cli.wire.operation import Operation

if TYPE_CHECKING:
    from syncr_cli.parser import Invocation, Parser, Verbs
    from syncr_cli.runtime import Runtime

NOUN = "plan"

OPERATION_DOCUMENT = "operation"


def register(nouns: Verbs, shared: Parser) -> None:
    """Put the three plan commands in the catalog."""
    verbs = add_verb(nouns, shared, noun=NOUN, noun_help="Read, solve, and approve a plan")
    showing = register_command(
        verbs,
        noun=NOUN,
        verb="show",
        summary=(
            "The live plan for a week, or for one date with --date. Exits 8 when the week cannot "
            "hold its commitments"
        ),
        handler=show,
        shared=shared,
        examples=(
            "syncr plan show",
            "syncr plan show --week 2026-W07",
            "syncr plan show --date 2026-02-10",
        ),
    )
    showing.add_argument(
        "--date",
        dest="on",
        type=stated_date,
        metavar="DATE",
        help="one date's ledger instead of the week's, as 2026-02-10",
    )
    solving = register_command(
        verbs,
        noun=NOUN,
        verb="solve",
        summary=(
            "Request a solve and print the operation, exiting 0 immediately. With --wait, poll it "
            "to a terminal status and exit by that status: 0, 1, 9, or 10"
        ),
        handler=solve,
        shared=shared,
        examples=(
            "syncr plan solve --week 2026-W07",
            "syncr plan solve --week 2026-W07 --wait",
            "syncr plan solve --wait --poll-interval 250 --timeout 120",
            "syncr plan solve --immediate --wait",
        ),
    )
    solving.add_argument(
        "--wait",
        action="store_true",
        help="poll the operation until it is terminal or the timeout runs out, and exit by what "
        "it ended as",
    )
    solving.add_argument(
        "--immediate",
        action="store_true",
        help="bypass the debounce window this solve would otherwise wait out",
    )
    register_command(
        verbs,
        noun=NOUN,
        verb="approve",
        summary=(
            "Approve the pending proposal, making it the plan of record. Exits 6 when the slot has "
            "been cleared"
        ),
        handler=approve,
        shared=shared,
        examples=("syncr plan approve", "syncr plan approve --week 2026-W07 --json"),
    )


def show(runtime: Runtime, invocation: Invocation) -> CliResult:
    """The week's ledger, or one date's."""
    on = invocation.value("on", date)
    if on is not None:
        return _day(runtime, on)
    return read_week(runtime).as_result()


def solve(runtime: Runtime, invocation: Invocation) -> CliResult:
    """Ask for a solve, and follow it when asked to."""
    iso_week = str(runtime.settings.week)
    immediate = bool(invocation.value("immediate", bool))
    dispatched = Operation.read(
        runtime.client.request_solve(iso_week, immediate=immediate), OPERATION_DOCUMENT
    )
    if not invocation.value("wait", bool):
        return CliResult.dispatched(
            dispatched,
            data=SolveRequestedView(
                iso_week=iso_week, immediate=immediate, operation_payload=dispatched.payload
            ),
        )
    return _waited(runtime, iso_week, dispatched)


def approve(runtime: Runtime, invocation: Invocation) -> CliResult:
    """Approve what the week is proposing, and answer with what that wrote."""
    iso_week = str(runtime.settings.week)
    approved = WeekApproved.read(
        runtime.client.approve_week(iso_week, key=invocation.idempotency_key({"isoWeek": iso_week}))
    )
    return CliResult.succeeded(WeekApprovedView(approved=approved), operation=approved.projection)


def _day(runtime: Runtime, on: date) -> CliResult:
    """One date's ledger: what has ended, what has not, and what the log says about each."""
    return CliResult.succeeded(DayLedgerView(day=DayLedger.read(runtime.client.read_day(on))))


def _waited(runtime: Runtime, iso_week: str, dispatched: Operation) -> CliResult:
    """Poll the solve this invocation dispatched, and answer by how it ended.

    A timeout is reported as a failure carrying the operation, so an agent resumes from
    ``operation.id`` rather than parsing a sentence for it. Every other ending answers with the
    week's own summary, which is what makes the figures a wait reports the same figures ``week
    show`` reports.
    """
    try:
        settled = wait_for_operation(
            client=runtime.client,
            operation_id=dispatched.id,
            poll_interval_ms=runtime.settings.poll_interval_ms,
            timeout_s=runtime.settings.timeout_s,
            sleep=runtime.host.sleep,
            monotonic=runtime.host.monotonic,
        )
    except WaitTimedOut as ran_out:
        return CliResult.failed(ran_out.problem, operation=ran_out.operation)
    read = read_week(runtime)
    return CliResult.dispatched(
        settled,
        data=SolveSettledView(iso_week=iso_week, ledger=read.ledger),
        verdict=read.view.verdict,
    )
