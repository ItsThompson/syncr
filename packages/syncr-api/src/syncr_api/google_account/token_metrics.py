"""``syncr_write_target_token_age_seconds``: why the age is the CONDITION's, not a token's.

The gauge and ``WriteTargetTokenExpiring`` are defined here as the critical alert on it: "the plan
silently stops reaching the phone. The most dangerous failure in the product." An audit found that
no process exported the metric, so that alert could not fire. This is it.

**The age measured is the age of the FAILURE, not of the credential.** A refresh token has no
expiry a client can read, and a healthy credential that has been connected for a year is not a
condition anyone should be paged about. What ``refresh_failing_since`` records is when refreshing
STARTED failing, which is the quantity a threshold is stated against: writes have not reached the
calendar since that instant. A credential refreshing normally reports zero.

**Set from stored rows on a duty that runs whether or not anything else happens.** A gauge written
where a refresh is attempted is absent exactly when refreshes have stopped being attempted, which
is the other finding stated as a rule. So the reading is one row per tenant, taken from the
credential table on a schedule, and a deployment with no Google connection reports zero rather than
nothing: an absent series and a healthy one must not be the same reading.

**A TENANT THAT STOPS BEING ENUMERATED HAS ITS SERIES REMOVED.** The alert reads a maximum across
tenants, and nothing in the client library removes a child, so in a long-lived worker a departed
tenant whose credential was failing would hold this deployment's most dangerous alert firing forever
with no repair available. :func:`forget_tenants` is that reconciliation, and it mirrors the one the
two per-source gauges carry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Gauge

from syncr_common.metrics import REGISTRY

if TYPE_CHECKING:
    from collections.abc import Collection
    from datetime import datetime

    from syncr_api.google_account.records import GoogleCredentialRecord
    from syncr_domain.identifiers import TenantId

TOKEN_AGE = Gauge(
    "syncr_write_target_token_age_seconds",
    "Seconds the write target's credential has been failing to refresh. Zero when it is not.",
    labelnames=("tenant",),
    registry=REGISTRY,
)

# Which tenants this process has published a series for, so a tenant that disappears can have it
# removed. Tracked here for the same reason the source gauges track theirs: the client library
# offers no public way to enumerate a family's children.
_PUBLISHED: set[str] = set()


def observed_credential(
    tenant_id: TenantId, credential: GoogleCredentialRecord | None, *, now: datetime
) -> None:
    """Set the gauge for one tenant, from the row as stored.

    A tenant with no credential and a tenant whose credential refreshes normally both report zero,
    which is the same thing to an alert: the plan is reaching the calendar, or there is no calendar
    for it to reach. What the alert fires on is the third case, and only that case grows.
    """
    failing_since = credential.refresh_failing_since if credential is not None else None
    TOKEN_AGE.labels(tenant=str(tenant_id)).set(
        0.0 if failing_since is None else max((now - failing_since).total_seconds(), 0.0)
    )
    _PUBLISHED.add(str(tenant_id))


def forget_tenants(present: Collection[TenantId]) -> None:
    """Remove this gauge's series for every tenant the deployment no longer enumerates.

    Called with the tenants the duty ENUMERATED rather than the ones it read successfully. A
    contained fault means a tenant went unobserved this tick, not that it is gone: forgetting it
    would delete a live series on a transient fault, and the alert would then read healthy for the
    one tenant whose state could not be established.
    """
    kept = {str(one) for one in present}
    for tenant in _PUBLISHED - kept:
        TOKEN_AGE.remove(tenant)
        _PUBLISHED.discard(tenant)
