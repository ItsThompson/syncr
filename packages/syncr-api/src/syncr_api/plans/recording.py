"""``VerdictRecorder``: the only writer of a ``VerdictEvent``, bound to the surface that asked.

One method, and what it holds is the decision: read the last thing said about this week, decide
whether this verdict says something new, and append a row if it does. A caller that computed a
verdict calls it unconditionally and does not know the rule, which is what keeps the twelve-pin
burst from writing twelve rows in one place rather than in five.

**The surface and the session mode are both bound at construction, in the wiring of each caller.**
So a service never passes either, no code path can pass a surface that is not its own, and the
enumeration of who records a transition is the set of places a recorder is composed.
``tests/test_verdict_surfaces.py`` reads that set out of the source and holds it against the six
members.

**``session_mode_active`` has no default.** Only the caller knows whether the weekly session is
open, because it is a mode of the client's own screen. A request carries it in a header the edge
reads; the worker's two callers bind ``False`` as a literal beside the reason, and a defaulted
parameter is how a third caller would acquire that answer without stating it.

**No transaction of its own and no session of its own.** The repository is composed from the
caller's session, so a transition commits with the mutation or the job that computed the verdict or
not at all. A recorder is therefore as cheap to hold as a repository, which is why each request
builds one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.verdict_metrics import VERDICT_TRANSITIONS, as_label
from syncr_api.plans.verdict_transitions import as_recorded, is_a_transition
from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from syncr_api.plans.records import VerdictEventRecord
    from syncr_api.plans.surfaces import VerdictSurface
    from syncr_api.plans.verdict_events import VerdictEventRepository
    from syncr_domain.feasibility import Verdict
    from syncr_domain.identifiers import OperationId
    from syncr_domain.weeks import IsoWeek

_log = get_logger("syncr.verdicts")

# What a caller with no weekly session reports, which is every caller that is not a browser with one
# open: the worker's two, and a client that has no session concept at all. Named so the two worker
# call sites state the same thing rather than a bare ``False`` each.
NO_SESSION_IS_OPEN = False


class VerdictRecorder:
    """Records one week's verdict transitions from one surface, for one caller's session state."""

    def __init__(
        self,
        events: VerdictEventRepository,
        *,
        surface: VerdictSurface,
        session_mode_active: bool,
    ) -> None:
        self._events = events
        self._surface = surface
        self._session_mode_active = session_mode_active

    async def record(
        self,
        iso_week: IsoWeek,
        verdict: Verdict,
        *,
        caused_by: OperationId | None = None,
    ) -> VerdictEventRecord | None:
        """Append this verdict if it is a transition, and answer with the row, or with ``None``.

        ``None`` is the ordinary answer: a verdict recomputed identically is not news. The caller
        that wants to know which way a week moved reads the row it is handed rather than the verdict
        it passed, because the row carries the reading the corpus holds.
        """
        recorded = as_recorded(
            verdict,
            iso_week=iso_week,
            surface=self._surface,
            session_mode_active=self._session_mode_active,
            caused_by=caused_by,
        )
        if not is_a_transition(recorded, since=await self._events.latest(iso_week)):
            return None

        written = await self._events.append(recorded)
        # Incremented inside the caller's transaction, so a failure after this leaves the counter
        # one above the row count until the process restarts. The ROW is the fact: the product
        # metric is computed from the table by its own job, and this family is the operational read.
        VERDICT_TRANSITIONS.labels(
            provenance=written.provenance.value,
            feasible=as_label(written.feasible),
            surface=written.surface.value,
        ).inc()
        _log.info(
            "verdicts.transition.recorded",
            iso_week=str(iso_week),
            verdict_event_id=str(written.id),
            surface=written.surface.value,
            provenance=written.provenance.value,
            feasible=written.feasible,
            shortfall_minutes=written.shortfall_minutes,
            shortfall_kinds=[one.value for one in written.shortfall_kinds],
            session_mode_active=written.session_mode_active,
            input_version=written.input_version,
        )
        return written
