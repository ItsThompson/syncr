"""Reading a value a caller stated on the command line, and refusing one that names nothing.

Every function here is an argparse ``type``, and every refusal is this package's
:class:`~syncr_cli.errors.UsageError` rather than the framework's. argparse catches ``ValueError``
and ``TypeError`` from a ``type`` and re-words them, which would lose the sentence that says what
the accepted form is; a ``UsageError`` propagates to the runner, which answers with the wrapper an
agent parses and exits 2.

**An instant needs an explicit offset.** A local wall time is exactly what this wire does not carry,
so one arriving is refused rather than interpreted with the machine's own zone: a caller in a
different zone from the server would otherwise pin a block an hour from where they meant.
"""

from __future__ import annotations

from datetime import date, datetime

from syncr_cli.errors import UsageError

# The forms a caller states, in the words a refusal names them by.
DATE_EXAMPLE = "2026-02-10"
INSTANT_EXAMPLE = "2026-02-10T09:00:00+00:00"


def stated_date(value: str) -> date:
    """A calendar date, as ``2026-02-10``."""
    try:
        return date.fromisoformat(value.strip())
    except ValueError as error:
        raise UsageError(
            f"{value!r} is not an ISO date such as '{DATE_EXAMPLE}'. Nothing was changed."
        ) from error


def stated_instant(value: str) -> datetime:
    """An instant with an explicit UTC offset, as ``2026-02-10T09:00:00+00:00``."""
    stated = value.strip()
    try:
        moment = datetime.fromisoformat(stated)
    except ValueError as error:
        raise UsageError(
            f"{value!r} is not an RFC 3339 instant such as '{INSTANT_EXAMPLE}'. Nothing was "
            "changed."
        ) from error
    if moment.tzinfo is None:
        raise UsageError(
            f"{value!r} states no UTC offset, and this CLI will not guess a zone for an instant. "
            f"State one, as '{INSTANT_EXAMPLE}'. Nothing was changed."
        )
    return moment


def stated_identifier(value: str) -> str:
    """An identifier a caller read out of an earlier response.

    Checked for emptiness only. What an identifier looks like is the api's to say, and a client
    that enforced a shape here would refuse a form a later api legitimately mints.
    """
    stated = value.strip()
    if not stated:
        raise UsageError("an identifier was expected and nothing was stated. Nothing was changed.")
    return stated
