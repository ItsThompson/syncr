"""What ``plan solve`` answers with, in both renderings: the request, and what a wait settled on.

Two shapes, and the difference between them is the whole of ``--wait``. A dispatch says which week
was asked for and nothing else, because the plan does not exist yet: the operation the shared
renderer prints beside it is what a caller polls. A settled wait says what the solve produced.

**A settled wait prints the plan summary, and the summary is the week's own.** It is the ledger's
heading group, so the figures a wait reports and the figures ``week show`` reports are the same
figures rather than a second arithmetic that can disagree. The day rows are deliberately absent: a
wait reports an outcome, and ``week show`` is the command that prints a week.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from syncr_cli.rendering.views import PlainView

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_cli.rendering.ledger import WeekLedger
    from syncr_cli.wire.reading import JsonMapping

_LABEL: Final = 10

REQUESTED: Final = "requested"
IMMEDIATE: Final = "immediately, bypassing the debounce window"
DEBOUNCED: Final = "due one debounce window from now"


@dataclass(frozen=True, slots=True)
class SolveRequestedView(PlainView):
    """What ``plan solve`` answers with when it does not wait."""

    iso_week: str
    immediate: bool
    operation_payload: JsonMapping

    @property
    def payload(self) -> JsonMapping:
        """The operation the api answered with, which is the whole of what a dispatch produced.

        The same object the wrapper's ``operation`` member carries. Repeated rather than left null,
        because ``data`` is what an agent reads for the command's own answer and a dispatch's answer
        is the operation: a null there would make this the one command whose payload is absent.
        """
        return self.operation_payload

    def header_lines(self) -> list[str]:
        return [
            f"{'solve':<{_LABEL}} {REQUESTED} for {self.iso_week}",
            f"{'when':<{_LABEL}} {IMMEDIATE if self.immediate else DEBOUNCED}",
        ]


@dataclass(frozen=True, slots=True)
class SolveSettledView(PlainView):
    """What ``plan solve --wait`` answers with once the operation is terminal.

    Wraps the week's ledger rather than re-deriving a summary, and drops its body: the figures are
    the week's own and the day rows belong to ``week show``.
    """

    iso_week: str
    ledger: WeekLedger

    @property
    def payload(self) -> JsonMapping:
        return self.ledger.payload

    def header_lines(self) -> list[str]:
        return [f"{'solved':<{_LABEL}} {self.iso_week}", "", *self.ledger.header_lines()]

    def render_deadline(self, moment: datetime) -> str:
        """A shortfall's deadline, in the zone the week it belongs to is lived in on that date."""
        return self.ledger.render_deadline(moment)
