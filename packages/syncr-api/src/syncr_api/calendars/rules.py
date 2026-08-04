"""The two role rules and the horizon rule, as pure functions over one source.

They live apart from the service because each is an invariant of the domain rather than a step
in a request, and because the one that matters most is easy to state and easy to lose:

**A calendar acting as an anchor source is never the write target.** The write target is
reconciled destructively over its horizon, so a calendar syncr reads and a calendar syncr
overwrites cannot be the same one. If they were, every solve would treat the previous solve's
output as immovable external commitments, and the reconciliation would delete the user's real
calendar.

Each rejection names the surviving capability, because a notice that says only what broke
leaves the user unable to decide what to do next.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.calendars.config import GOOGLE, HORIZON_DAYS_MAX, HORIZON_DAYS_MIN, WRITE_TARGET
from syncr_api.core.errors import Conflict, ValidationFailed

if TYPE_CHECKING:
    from collections.abc import Collection

    from syncr_api.calendars.config import CalendarProvider
    from syncr_api.calendars.records import CalendarSourceRecord


def require_no_anchor_history(source: CalendarSourceRecord) -> None:
    """Reject the write-target role on a source syncr has already read anchors from.

    "Active" is read as "has ever synced successfully" rather than as "currently reports
    anchors". A feed that read zero events last night is still a feed the user subscribed to,
    and designating it would hand destructive write access to a calendar they read elsewhere.
    """
    if source.sync_state.last_success_at is None and source.sync_state.anchors_current == 0:
        return
    raise ValidationFailed(
        f"{source.display_name!r} is an active anchor source: syncr has already read "
        f"{source.sync_state.anchors_current} commitments from it. The calendar syncr writes to "
        "is reconciled destructively and its contents are overwritten, so it cannot also be a "
        "calendar syncr reads. Add a new, empty calendar for the plan. Nothing was changed; "
        "this source still contributes its anchors."
    )


def require_no_write_target(held: CalendarSourceRecord | None) -> None:
    """Reject a second write target, naming the one that holds the role.

    The partial unique index is the guarantee; this is what turns it into an answer a caller can
    act on rather than an integrity error.
    """
    if held is None:
        return
    raise Conflict(
        f"{held.display_name!r} is already the calendar syncr writes the plan to, and there can "
        "only be one. Remove that role from it first. Reading anchors from every source still "
        "works, and the plan still reaches the calendar already set."
    )


def require_the_write_target(source: CalendarSourceRecord) -> None:
    """Reject a horizon on an anchor source.

    A projection bound on a read-only feed describes nothing: syncr reads an anchor source over
    whatever span the assembler asks for, and writes to the target over the horizon.
    """
    if source.role == WRITE_TARGET:
        return
    raise ValidationFailed(
        f"{source.display_name!r} is an anchor source, and a projection horizon belongs to the "
        "calendar syncr writes to. Nothing was changed; this source still contributes its "
        "anchors."
    )


def require_a_projectable_horizon(horizon_days: int) -> None:
    """Reject a horizon the projection cannot use.

    Restated here as well as in the request schema, because the service is a public interface: a
    caller reaching it without the HTTP boundary would otherwise get an ``IntegrityError`` from
    the check constraint where the boundary gives a stated 422.
    """
    if HORIZON_DAYS_MIN <= horizon_days <= HORIZON_DAYS_MAX:
        return
    raise ValidationFailed(
        f"A projection horizon of {horizon_days} days is outside the range syncr writes, "
        f"{HORIZON_DAYS_MIN} to {HORIZON_DAYS_MAX} days. Nothing was changed; the plan still "
        "projects over the horizon already set."
    )


def require_a_readable_provider(
    source: CalendarSourceRecord, *, readable: Collection[CalendarProvider]
) -> None:
    """Reject a sync on a provider this deployment cannot read.

    The readable set is the syncer's own adapter map rather than a constant, so the rule states what
    this process can actually do. A Google source on a deployment with no Google credentials is the
    live case: handed to no adapter it would answer nothing, and handed to the wrong one it would be
    fetched as a URL and recorded as a transport failure, so the panel would tell the user their
    calendar is broken when the truth is that this deployment cannot read it yet.
    """
    if source.provider in readable:
        return
    raise ValidationFailed(
        f"{source.display_name!r} is a {source.provider} calendar, and this deployment is not "
        "configured to read one. Nothing was changed and nothing about this source is wrong. "
        f"Every {', '.join(sorted(readable))} source still syncs."
    )


def require_a_google_source(source: CalendarSourceRecord) -> None:
    """Reject a Google-only read on a source of another provider.

    Listing an account's calendars is a question about an OAuth account, and an ICS feed has none:
    a feed is one calendar at one address, so there is no list to choose from.
    """
    if source.provider == GOOGLE:
        return
    raise ValidationFailed(
        f"{source.display_name!r} is a {source.provider} source, and only a Google account holds a "
        "list of calendars to choose from: a feed is one calendar at one address. Nothing was "
        "changed; this source still contributes its anchors."
    )
