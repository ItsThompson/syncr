"""``block done``, ``block skip``, ``block partial``, and ``block move``.

Four commands over two acts. The first three record what happened to a block, which is a statement
about the past; the fourth moves one, which constrains the future by creating a pin.

**Recording an outcome does not confirm the day.** A block marked skipped on a day nobody has
answered for is a statement about the block, and the day stays excluded from reviews and from
learning until ``day confirm`` settles it.

**A move reports the resulting verdict.** The verdict is computed from capacity arithmetic and needs
no solve to complete, which is what lets one command say immediately that a change broke the week:
an infeasible verdict exits 8, which is information rather than an error. The solve the edit asked
for is printed beside it so a caller can follow it without guessing an identifier.

**The week is named in the body because a block id cannot carry it.** A block's identity is a digest
of the week and the binding, so the week cannot be read back out of it, and the alternative is a
walk over every revision the tenant has stored. It comes from ``--week``, which defaults to this
machine's current ISO week.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Final

from syncr_cli.arguments import stated_identifier, stated_instant
from syncr_cli.parser import add_verb, register_command
from syncr_cli.rendering.edit_views import BlockMovedView, OutcomeRecordedView
from syncr_cli.results import CliResult
from syncr_cli.wire.day import Outcome
from syncr_cli.wire.pin import Pinned

if TYPE_CHECKING:
    import argparse

    from syncr_cli.parser import Invocation, Parser, Verbs
    from syncr_cli.runtime import Runtime
    from syncr_cli.wire.reading import JsonMapping

NOUN = "block"

# The three outcome states these commands record. `moved` and `presumed` are deliberately absent:
# `moved` describes a past that a `block move` pin does not, and `presumed` is what a block already
# is, so recording it says only that nothing else happened.
COMPLETED: Final = "completed"
SKIPPED: Final = "skipped"
PARTIAL: Final = "partial"


def register(nouns: Verbs, shared: Parser) -> None:
    """Put the four block commands in the catalog."""
    verbs = add_verb(
        nouns, shared, noun=NOUN, noun_help="Record what happened to a block, or move one"
    )
    _block_argument(
        register_command(
            verbs,
            noun=NOUN,
            verb="done",
            summary="Record a completed outcome for one block",
            handler=complete,
            shared=shared,
            examples=("syncr block done <block-id>", "syncr block done <block-id> --week 2026-W07"),
        )
    )
    _block_argument(
        register_command(
            verbs,
            noun=NOUN,
            verb="skip",
            summary="Record a skipped outcome for one block. The day stays unconfirmed",
            handler=skip,
            shared=shared,
            examples=("syncr block skip <block-id>",),
        )
    )
    partially = register_command(
        verbs,
        noun=NOUN,
        verb="partial",
        summary="Record a partial outcome with the minutes it really took",
        handler=partial,
        shared=shared,
        examples=(
            "syncr block partial <block-id> --minutes 45",
            "syncr block partial <block-id> --minutes 45 --json",
        ),
    )
    _block_argument(partially)
    partially.add_argument(
        "--minutes",
        required=True,
        type=int,
        metavar="MINUTES",
        help="how many minutes the block really took. A partial of no minutes is a skip and has "
        "its own command",
    )
    moving = register_command(
        verbs,
        noun=NOUN,
        verb="move",
        summary=(
            "Move a block, creating a pin, and report the resulting verdict. Exits 8 when the week "
            "can no longer hold its commitments"
        ),
        handler=move,
        shared=shared,
        examples=(
            "syncr block move <block-id> --to 2026-02-10T07:00:00+00:00",
            "syncr block move <block-id> --to 2026-02-10T07:00:00+00:00 --week 2026-W07",
        ),
    )
    _block_argument(moving)
    moving.add_argument(
        "--to",
        dest="start",
        required=True,
        type=stated_instant,
        metavar="INSTANT",
        help="where the block now begins, with a UTC offset. Its length is unchanged, because a "
        "move does not resize",
    )


def complete(runtime: Runtime, invocation: Invocation) -> CliResult:
    """Record that one block happened as planned."""
    return _record(runtime, invocation, state=COMPLETED)


def skip(runtime: Runtime, invocation: Invocation) -> CliResult:
    """Record that one block did not happen."""
    return _record(runtime, invocation, state=SKIPPED)


def partial(runtime: Runtime, invocation: Invocation) -> CliResult:
    """Record that one block happened for fewer minutes than it was given."""
    return _record(runtime, invocation, state=PARTIAL, minutes=invocation.required("minutes", int))


def move(runtime: Runtime, invocation: Invocation) -> CliResult:
    """Pin one block where the caller put it, and report what that did to the week."""
    iso_week = str(runtime.settings.week)
    block_id = invocation.required("block_id", str)
    body: JsonMapping = {
        "blockId": block_id,
        "start": invocation.required("start", datetime).isoformat(),
    }
    pinned = Pinned.read(
        runtime.client.create_pin(
            iso_week, body, key=invocation.idempotency_key({"isoWeek": iso_week, **body})
        )
    )
    return CliResult.succeeded(
        BlockMovedView(pinned=pinned), verdict=pinned.verdict, operation=pinned.operation
    )


def _record(
    runtime: Runtime, invocation: Invocation, *, state: str, minutes: int | None = None
) -> CliResult:
    """One recording, and the one shape all three of them take.

    The body carries the figure its state names and nothing else: the api refuses a body carrying
    both, so a client that sent a null minute count for a completion would be sending a value the
    state cannot read.
    """
    iso_week = str(runtime.settings.week)
    block_id = invocation.required("block_id", str)
    body: JsonMapping = {"isoWeek": iso_week, "state": state}
    if minutes is not None:
        body["actualMinutes"] = minutes
    recorded = Outcome.read(
        runtime.client.record_outcome(
            block_id, body, key=invocation.idempotency_key({"blockId": block_id, **body})
        )
    )
    return CliResult.succeeded(OutcomeRecordedView(outcome=recorded))


def _block_argument(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "block_id",
        metavar="BLOCK_ID",
        type=stated_identifier,
        help="the block, as the week's ledger spells its id",
    )
