"""How a projection fails, and the sentence every failure of it states.

Three types, and the distinction between the first two is the repair rather than the severity.

``ProjectionFailed``  the write was attempted and did not complete. Retrying may clear it.
``ProjectionRefused`` this deployment will not write at all. Retrying cannot clear it.
``ProjectionKeysCollide`` two events syncr intends share a key, which is a fault in syncr.

**A reconciliation that did not finish raises rather than answering.**
:class:`~syncr_api.calendars.projection.ReconcileResult` is the shape of a reconciliation that made
the target match the plan, and a partial write did not: a caller handed one would have to remember
to ask whether it was complete, and the one thing a destructive write path must never do is read as
a success when it is not. So the counts a failed attempt DID apply travel on the exception, where a
caller cannot ignore them and the metrics still record the writes that happened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_api.calendars.projection import ReconcileResult

if TYPE_CHECKING:
    from syncr_api.calendars.projection import ProjectionAction

# What every projection failure states about the target, because a notice that says only what broke
# leaves the reader unable to decide what to do next. The previous projection is untouched: a
# reconciliation writes only the difference, so a failed one leaves whatever last succeeded.
PREVIOUS_PROJECTION_STANDS: Final = (
    "The projection already on the calendar is untouched, so the plan your phone shows is the last "
    "one syncr wrote."
)


class ProjectionFailed(Exception):
    """A reconciliation that did not make the target match the plan, and what it did apply.

    ``applied`` holds the writes that DID land before the failure. They are carried rather than
    discarded because they happened: the events metric records them, and the next reconciliation
    converges from a fresh read of the target either way.
    """

    code: str = "projection_failed"

    def __init__(self, reason: str, *, applied: ReconcileResult | None = None) -> None:
        super().__init__(f"{reason} {PREVIOUS_PROJECTION_STANDS}")
        self.reason = reason
        self.applied = applied if applied is not None else ReconcileResult()

    def by_action(self) -> dict[ProjectionAction, int]:
        """The writes that landed, per action, so a failed attempt still reports them."""
        return dict(self.applied.by_action())


class ProjectionRefused(ProjectionFailed):
    """This deployment will not write to the target, so nothing was attempted.

    Its own code because the repair differs: a failure is retried and may clear, and a refusal holds
    until an operator changes the deployment or a user reconnects. Nothing reaches the provider, so
    ``applied`` is empty by construction rather than by accident.
    """

    code = "projection_refused"


class ProjectionKeysCollide(Exception):
    """Two events syncr intends share one key, so the diff could not pair them unambiguously.

    Not a ``ProjectionFailed``: nothing was attempted and the cause is in syncr rather than at the
    provider or in the deployment, so it reaches the runner's fault boundary as itself.
    """
