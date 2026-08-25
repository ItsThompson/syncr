"""Bounding one recurrence expansion from outside this process.

dateutil's ``next()`` cannot be interrupted from inside the call. A rule whose parts are each
inside the range RFC 5545 gives them but that can never be satisfied at once
(``FREQ=SECONDLY;BYMONTH=2;BYMONTHDAY=30;BYHOUR=2``) yields nothing while the expander walks
toward dateutil's maximum year, measured at 1,290 seconds in one call. The guards in
:mod:`syncr_api.calendars.ics_recurrence` pre-empt specific shapes of that failure and stay
standing; the class is not closed, and this module is what answers the rest of it.

**The boundary is a separate process.** Not a thread: a thread shares the interpreter's GIL,
so a CPU-bound expansion on one starves the api's event loop exactly as an inline call does.
Not a signal alarm: one fires only on the main thread of the main interpreter, so the api
process and the worker process would answer one feed two ways. A child process runs the
expansion on its own interpreter, so the waiting parent holds no GIL and a deadline is a
``poll`` timeout away.

**The parent enforces the deadline; the child knows nothing of time.** The child is ordinary
expansion code reading requests off a pipe. The parent waits at most ``deadline_seconds`` for
the answer; a wait that expires is answered by terminating the child (which is the reclaim:
nothing of the hung expansion survives it), raising a rejection that quotes the bounded rule
text, and replacing the worker before the next request.

**One feed pays at most one deadline.** A component whose expansion outlives the deadline has
also spent the feed's whole parse budget, so every later component is refused by the
between-components check in :mod:`syncr_api.calendars.ics_parse` without reaching this module.
A feed made entirely of unsatisfiable rules therefore costs its budget plus at most one
deadline, not one deadline per component.
"""

from __future__ import annotations

import multiprocessing
import queue
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from syncr_api.calendars.config import EXPANSION_DEADLINE_SECONDS, EXPANSION_POOL_SIZE
from syncr_api.calendars.ics_errors import UnparseableRecurrence
from syncr_api.calendars.ics_series import expand

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

    from syncr_api.calendars.ics_components import EventComponent
    from syncr_api.calendars.ics_series import Placement, Series
    from syncr_domain.intervals import Interval
    from syncr_domain.zones import ZoneProfile

# How much of a timed-out rule the rejection quotes, matching what the other rule rejections
# quote. The detail is bounded again where it is stored, but quoting a megabyte-wide rule here
# would build the string before anything bounded it.
_QUOTED_RULE_WIDTH: Final = 200

_OK: Final = "ok"
_FAULT: Final = "fault"

# The spawn context rather than fork: fork copies a multi-threaded api process, which risks
# deadlock in the child, and a copied interpreter carries whatever threads and locks the parent
# happened to hold. Spawn starts a plain interpreter that imports the worker target by name,
# which costs about a second per worker once and nothing per expansion after that.
_CONTEXT: Final = "spawn"


def _serve(connection: Connection) -> None:
    """Expand rules until the pipe closes. This runs in the child process.

    A fault becomes the ANSWER rather than an exit: a guard's refusal is how a component is
    rejected, so it travels back for the parent to raise where the caller expects it. Anything
    that kills the child anyway leaves the parent reading from a closed pipe, which the parent
    answers with a stated rejection and a fresh worker.
    """
    try:
        while True:
            master, series, horizon, profile = connection.recv()
            answer: tuple[str, Placement] | tuple[str, Exception]
            try:
                answer = (_OK, expand(master, series, horizon=horizon, profile=profile))
            except Exception as error:  # noqa: BLE001 - the refusal IS the answer
                answer = (_FAULT, error)
            connection.send(answer)
    except (EOFError, OSError):
        return


@dataclass(slots=True)
class _Worker:
    """One child process and the pipe it is reached through."""

    process: multiprocessing.process.BaseProcess
    connection: Connection

    def stop(self) -> None:
        """Terminate the child and wait for it, so no zombie is left behind."""
        self.process.terminate()
        self.process.join()
        self.connection.close()

    @property
    def alive(self) -> bool:
        return self.process.is_alive()


class ExpansionBound:
    """A pool of expansion processes whose deadlines this side of the pipe enforces.

    One instance serves any number of feeds and callers: workers are checked out of an idle set
    and returned to it, so concurrent parses share the pool up to its size. A worker lost to a
    timeout or to death is replaced automatically, and :attr:`replacements` counts the losses,
    which is how a test sees that a reclaim happened.
    """

    def __init__(
        self,
        *,
        deadline_seconds: float = EXPANSION_DEADLINE_SECONDS,
        size: int = EXPANSION_POOL_SIZE,
    ) -> None:
        self._deadline = deadline_seconds
        self._context = multiprocessing.get_context(_CONTEXT)
        self._idle: queue.Queue[_Worker] = queue.Queue()
        self._replacement_count = 0
        self._count_lock = threading.Lock()
        for _ in range(max(size, 1)):
            self._idle.put(self._start())

    @property
    def replacements(self) -> int:
        """How many workers were terminated and replaced, by timeout or by a lost worker."""
        return self._replacement_count

    def expand(
        self,
        master: EventComponent,
        series: Series,
        *,
        horizon: Interval,
        profile: ZoneProfile,
    ) -> Placement:
        """Every event ``master`` places inside ``horizon``, expanded in a child process.

        Raises :class:`UnparseableRecurrence`, quoting the rule text, if the expansion does not
        finish within the deadline. The text comes from the master itself, which the parent
        holds, so the rejection does not depend on the hung child reporting anything.

        The checkout below has no timeout because every path through this class hands its
        worker back or replaces it: a caller therefore waits at most one deadline for a busy
        pool, never forever. That invariant is what makes an unbounded ``get`` safe here; if a
        path ever stops returning workers, this is the line that turns it into a hang.
        """
        worker = self._idle.get()
        try:
            return self._answer(worker, master, series, horizon=horizon, profile=profile)
        finally:
            if worker.alive:
                self._idle.put(worker)
            else:
                # Terminated for exceeding the deadline, or dead on the pipe: either way the
                # reclaim is complete only when another worker stands ready in its place.
                with self._count_lock:
                    self._replacement_count += 1
                self._idle.put(self._start())

    def shutdown(self) -> None:
        """Stop every idle worker. Workers taken by a caller are daemons and die with us."""
        while True:
            try:
                self._idle.get_nowait().stop()
            except queue.Empty:
                return

    def _start(self) -> _Worker:
        parent, child = self._context.Pipe()
        process = self._context.Process(target=_serve, args=(child,), daemon=True)
        process.start()
        child.close()
        return _Worker(process=process, connection=parent)

    def _answer(
        self,
        worker: _Worker,
        master: EventComponent,
        series: Series,
        *,
        horizon: Interval,
        profile: ZoneProfile,
    ) -> Placement:
        connection = worker.connection
        try:
            connection.send((master, series, horizon, profile))
        except OSError as error:
            # The child was gone before it could take the request.
            raise UnparseableRecurrence(self._lost(master.recurrence.rule_text)) from error
        if connection.poll(self._deadline):
            try:
                verdict, answer = connection.recv()
            except (EOFError, OSError) as error:
                # The child died mid-request rather than past the deadline: a magnitude big
                # enough to exhaust the machine kills the expander exactly as a hang would,
                # so it gets the same kind of answer, but names what happened.
                raise UnparseableRecurrence(self._lost(master.recurrence.rule_text)) from error
        else:
            worker.stop()
            raise UnparseableRecurrence(self._refusal(master.recurrence.rule_text))
        if verdict == _FAULT:
            raise answer
        return cast("Placement", answer)

    def _refusal(self, rule_text: str | None) -> str:
        """Why a component produced nothing: its rule did not finish inside the deadline."""
        return (
            f"the recurrence rule {self._quoted(rule_text)} did not finish expanding within "
            f"{self._deadline:g} seconds, so syncr will not read it"
        )

    def _lost(self, rule_text: str | None) -> str:
        """Why a component produced nothing: its expander stopped before answering.

        Stated apart from the deadline expiry so a reader can tell a rule that ran out of
        time from one whose process died under it.
        """
        return (
            f"the recurrence rule {self._quoted(rule_text)} stopped being expanded before it "
            "finished, so syncr will not read it"
        )

    @staticmethod
    def _quoted(rule_text: str | None) -> str:
        if rule_text is None:
            return "a recurrence rule"
        if len(rule_text) <= _QUOTED_RULE_WIDTH:
            return repr(rule_text)
        return f"a rule of {len(rule_text)} characters"


_default_bound: ExpansionBound | None = None
_bound_lock = threading.Lock()


def default_bound() -> ExpansionBound:
    """The shared bound every parse uses unless it is handed one.

    Built on first use rather than at import, so importing the package spawns no process and
    tests that never parse a feed pay nothing.
    """
    global _default_bound
    if _default_bound is None:
        with _bound_lock:
            if _default_bound is None:
                _default_bound = ExpansionBound()
    return _default_bound
