"""Every table, column and JSONB key this job reads, in one place, and why they are restated.

The api owns these names. This package cannot import it: the api image must not carry scipy, so the
api cannot depend on this member, so this member cannot borrow the api's repositories. The job's I/O
therefore has to be here, and the price is one restated spelling.

**The price is paid down by ``tests/test_solver_agreement.py``**, which holds each name against the
api's own constant in one process. That test is why the names below are constants rather than string
literals inside a query: a literal cannot be crossed against anything.

Reads only, plus ONE insert. There is no ``UPDATE`` and no ``DELETE`` anywhere in this subpackage,
and the three tables the learning layer must never write are read through select statements that
name their columns: the layer is a reader of facts and a writer of parameters.
"""

from __future__ import annotations

from typing import Final

# ---------------------------------------------------------------------------
# The tables. Four are facts about weeks that happened, two are declarations, one is the artefact.
# ---------------------------------------------------------------------------

TENANTS: Final = "tenants"
SETTINGS: Final = "settings"
AREAS: Final = "areas"
PLAN_REVISIONS: Final = "plan_revisions"
BLOCK_OUTCOMES: Final = "block_outcomes"
EDIT_EVENTS: Final = "edit_events"
PINS: Final = "pins"
OFF_PLAN_PERIODS: Final = "off_plan_periods"
WEIGHT_SETS: Final = "weight_sets"

READ_TABLES: Final[tuple[str, ...]] = (
    TENANTS,
    SETTINGS,
    AREAS,
    PLAN_REVISIONS,
    BLOCK_OUTCOMES,
    EDIT_EVENTS,
    PINS,
    OFF_PLAN_PERIODS,
    WEIGHT_SETS,
)
"""Every table this job may touch. The one it also writes is ``weight_sets`` and no other."""

WRITE_TABLE: Final = WEIGHT_SETS
"""The one table this job writes, and it only ever appends to it."""

NEVER_WRITTEN: Final[tuple[str, ...]] = (PLAN_REVISIONS, PINS, BLOCK_OUTCOMES)
"""The three the learning layer must never write. Asserted over this subpackage's own source."""

# ---------------------------------------------------------------------------
# The columns each read names.
# ---------------------------------------------------------------------------

TENANT_ID: Final = "tenant_id"
ID: Final = "id"
ISO_WEEK: Final = "iso_week"
CREATED_AT: Final = "created_at"
DOCUMENT: Final = "document"
BLOCK_ID: Final = "block_id"
STATE: Final = "state"
ACTUAL_MINUTES: Final = "actual_minutes"
ACTUAL_STARTS_AT: Final = "actual_starts_at"
ACTUAL_ENDS_AT: Final = "actual_ends_at"
OCCURRED_AT: Final = "occurred_at"
CONFIRMED_AT: Final = "confirmed_at"
OBJECTIVE_DELTA: Final = "objective_delta"
CONTEXT: Final = "context"
WEIGHT_SET_VERSION: Final = "weight_set_version"
BINDING: Final = "binding"
STARTS_AT: Final = "starts_at"
# Where the plan of record held a pinned block before the pin. Read because promotion detection
# drops a pin that moved nothing, and this is what says whether one did.
SUPERSEDED_STARTS_AT: Final = "superseded_starts_at"
SPAN_START: Final = "start"
SPAN_END: Final = "end"
HOME_ZONE: Final = "home_zone"
NAME: Final = "name"
VERSION: Final = "version"
ACTIVE: Final = "active"

# ---------------------------------------------------------------------------
# The keys inside the two JSONB documents this job reads.
# ---------------------------------------------------------------------------

# A stored plan document. Three of its fields are what a fitter reads: the blocks, each block's own
# interval and Area, and the zone profile the week was computed under.
DOCUMENT_BLOCKS: Final = "blocks"
DOCUMENT_ZONE_BY_DATE: Final = "zone_by_date"
BLOCK_INTERVAL: Final = "interval"
BLOCK_BINDING: Final = "binding"
BLOCK_AREA_ID: Final = "area_id"
INTERVAL_START: Final = "start"
INTERVAL_END: Final = "end"

# A stored binding, which four tables carry and one document nests.
BINDING_KIND: Final = "kind"
BINDING_ENTITY_ID: Final = "entity_id"
BINDING_OCCURRENCE_KEY: Final = "occurrence_key"
BINDING_SPLIT_INDEX: Final = "split_index"

# A stored edit context. Two of its twenty-five fields are what the weight fit reads.
CONTEXT_MEASUREMENT_DELTA: Final = "measurement_delta"
CONTEXT_INSIDE_OFF_PLAN: Final = "inside_off_plan"

# The weight-set row's own twelve non-key columns. Named here for the reason every other name in
# this module is: a literal inside a query cannot be crossed against anything, and
# `tests/test_solver_agreement.py` crosses each of these against `WeightSet.__table__`.
ORIGIN: Final = "origin"
DEADLINE_RISK: Final = "deadline_risk"
BUDGET_DEVIATION: Final = "budget_deviation"
TIME_OF_DAY_MISFIT: Final = "time_of_day_misfit"
FRAGMENTATION: Final = "fragmentation"
CHURN: Final = "churn"
CONTEXT_SWITCH: Final = "context_switch"
STALENESS: Final = "staleness"
DURATION_MULTIPLIER: Final = "duration_multiplier"
TIME_OF_DAY_FITNESS: Final = "time_of_day_fitness"
SKIP_PROBABILITY: Final = "skip_probability"
CONTEXT_SWITCH_COST: Final = "context_switch_cost"
CHURN_TOLERANCE: Final = "churn_tolerance"
FITTED_AT: Final = "fitted_at"
MATURITY: Final = "maturity"

WEIGHT_SET_COLUMNS: Final[tuple[str, ...]] = (
    ORIGIN,
    DEADLINE_RISK,
    BUDGET_DEVIATION,
    TIME_OF_DAY_MISFIT,
    FRAGMENTATION,
    CHURN,
    CONTEXT_SWITCH,
    STALENESS,
    DURATION_MULTIPLIER,
    TIME_OF_DAY_FITNESS,
    SKIP_PROBABILITY,
    CONTEXT_SWITCH_COST,
    CHURN_TOLERANCE,
    FITTED_AT,
    MATURITY,
)
"""Every column the one insert names beyond the three keys, so the set is crossed at once."""
