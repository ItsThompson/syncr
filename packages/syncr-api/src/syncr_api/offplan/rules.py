"""What an off-plan declaration has to satisfy, and the status each rejection carries.

Two pieces, and neither states a rule of its own. The rules are
``syncr_domain.off_plan``'s: the bounds run forward, both land on the quarter hour, and no two
periods of one tenant cover a common instant. What lives here is the translation from a domain
rejection into the status the boundary owes it, and the one place a candidate is composed with
the periods already stored.

An overlap is a state conflict, so 409: the request was well formed and the stored periods are
what refuses it. Everything else the off-plan rules reject is a bad value in the request, so
422. Both details name the offending instants, because "that overlaps something" without
saying what is a message a user cannot act on.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from syncr_api.core.errors import Conflict, ValidationFailed
from syncr_domain.intervals import IntervalError
from syncr_domain.off_plan import OffPlanError, OffPlanPeriod, OverlappingOffPlanError

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from syncr_api.offplan.records import OffPlanPeriodRecord
    from syncr_domain.identifiers import OffPlanPeriodId


def find_period(
    period_id: OffPlanPeriodId, stored: Sequence[OffPlanPeriodRecord]
) -> OffPlanPeriodRecord | None:
    """The period with this identifier among ones already read, or ``None``."""
    return next((record for record in stored if record.id == period_id), None)


def others_than(
    period_id: OffPlanPeriodId | None, stored: Sequence[OffPlanPeriodRecord]
) -> tuple[OffPlanPeriod, ...]:
    """The stored periods a candidate is checked against, as domain values.

    ``period_id`` is the row being edited, which is left out so a period is not compared
    against its own stored self: every patch would otherwise overlap and be refused. ``None``
    leaves every stored period in, which is what a new declaration is checked against.
    """
    return tuple(
        record.as_domain() for record in stored if period_id is None or record.id != period_id
    )


@contextmanager
def stated_rejection() -> Iterator[None]:
    """Turn an off-plan rejection into the status the boundary owes it.

    ``OverlappingOffPlanError`` is caught before its own base class, because it is a subclass
    of ``OffPlanError`` and the order of ``except`` clauses is what decides which of the two
    statuses an overlap answers with.
    """
    try:
        yield
    except OverlappingOffPlanError as error:
        raise Conflict(
            f"That span overlaps an off-plan period already declared: {error}. Nothing was "
            "changed, and every period already declared still reads as it did. Shorten or "
            "remove the overlapping period and declare this span again. Two spans that abut "
            "exactly are accepted, because adjacency is not overlap: a period may end at "
            "09:00 and the next begin at 09:00."
        ) from error
    except (OffPlanError, IntervalError) as error:
        raise ValidationFailed(
            f"The span was not accepted: {error}. Nothing was changed, and every period "
            "already declared still reads as it did. A span runs forward and both of its "
            "bounds land on a quarter hour, so Friday 14:00 to Monday 09:00 is a period and "
            "Friday 14:07 is not a bound."
        ) from error
