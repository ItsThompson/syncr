"""The four product-metric families, and the two figures deliberately absent from them.

System metrics answer "is syncr healthy". These answer "is syncr working", meaning is it helping the
user, and they are the reason the product exists.

## Why the label carries a tenant and an Area IDENTIFIER

The table gives three of these no labels, because the deployment holds one user. A gauge
set in a loop over tenants would then hold whichever tenant was read last while reading as the
deployment's own figure, so the tenant is a label: the same reason every log line carries one.

``syncr_estimate_ape_median`` is labelled by area, and the label is the Area's IDENTIFIER, not its
name. An Area name is the user's own words: ``area_name="Job search"`` discloses exactly what a
block title does, which is why the logger redacts a field called ``name``. An exposition is no safer
a place for it. The dashboard resolves an identifier to a name at the point of display, where the
audience is the user rather than a scrape endpoint.

## Adherence rate is deliberately NOT a metric

Optimizing it rewards under-planning. A user who plans four hours a day and completes all of it
scores a perfect adherence rate while the product fails at its actual job, which is fitting a whole
life into a week. No family here counts completions against placements, and none should be added.

## Nothing here is a trace

There is no distributed tracing anywhere in this application, and its absence is a decision rather
than an omission: the value of tracing scales with the number of network hops between services, and
syncr has approximately one. A correlation id on every structured log line answers the same
questions without the infrastructure.
"""

from __future__ import annotations

from prometheus_client import Gauge

from syncr_common.metrics import REGISTRY

ESTIMATE_APE_MEDIAN = Gauge(
    "syncr_estimate_ape_median",
    "Median absolute percentage error between an estimated and an actual block duration.",
    labelnames=("tenant", "area"),
    registry=REGISTRY,
)

CAUGHT_EARLY_RATIO = Gauge(
    "syncr_infeasibility_caught_early_ratio",
    "Share of infeasibility episodes whose first row was recorded during a weekly session.",
    labelnames=("tenant",),
    registry=REGISTRY,
)

PROPOSAL_ACCEPTANCE_RATIO = Gauge(
    "syncr_proposal_acceptance_ratio",
    "Share of the proposal-class changes the user resolved that they accepted.",
    labelnames=("tenant",),
    registry=REGISTRY,
)

REPINS_PER_WEEK = Gauge(
    "syncr_repins_per_week",
    "Blocks pinned again after a solve had already moved them once, per week.",
    labelnames=("tenant",),
    registry=REGISTRY,
)

ENGAGEMENT_STREAK = Gauge(
    "syncr_engagement_streak_weeks",
    "Consecutive weeks with a weekly session run and five or more days confirmed. "
    "A week that is majority off-plan is skipped rather than counted as a failure.",
    labelnames=("tenant",),
    registry=REGISTRY,
)
