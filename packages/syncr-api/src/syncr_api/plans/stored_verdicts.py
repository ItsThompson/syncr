"""A verdict's stored form: written into the pending slot, and read back out of it.

The slot's ``verdict`` column is not nullable, because a proposal a user is asked to approve has to
be able to say what it fixes and what it still cannot. So a solve's verdict needs a stored spelling,
and it has exactly one, here, built from the same leaf forms every other stored plan value uses.

**Both directions, and the round trip is what proves the writer.** A serializer with no reader
cannot be shown to be faithful: a field silently dropped writes successfully forever. Reading is
also where a stored document becomes a value again, and the domain constructors are what refuse a
corrupt one, so ``rebuilt`` routes a domain refusal through this package's own corruption error
rather than restating each invariant here.

**A tradeoff's ``delta_minutes`` is optional and stays optional.** The enumerator states the three
cases where it can promise more than approving delivers, and a verdict that carried a figure for a
gap the enumerator could not size would be a promise nobody made.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.stored_values import (
    read_flag,
    read_id,
    read_instant,
    read_list,
    read_mapping,
    read_member,
    read_optional_id,
    read_optional_instant,
    read_optional_whole_number,
    read_text,
    read_whole_number,
    rebuilt,
    stored_id,
    stored_instant,
)
from syncr_domain.feasibility import Provenance, Shortfall, ShortfallKind, Tradeoff, Verdict
from syncr_domain.plan import AdjustmentKind

if TYPE_CHECKING:
    from syncr_api.core.columns import JsonDocument, JsonObject

FEASIBLE = "feasible"
PROVENANCE = "provenance"
COMPUTED_AT = "computedAt"
INPUT_VERSION = "inputVersion"
DISCRETIONARY_MINUTES = "discretionaryMinutes"
SHORTFALLS = "shortfalls"
TRADEOFFS = "tradeoffs"


def stored_verdict(verdict: Verdict) -> JsonObject:
    """One verdict, as the document the pending slot holds."""
    return {
        FEASIBLE: verdict.feasible,
        PROVENANCE: verdict.provenance.value,
        COMPUTED_AT: stored_instant(verdict.computed_at),
        INPUT_VERSION: verdict.input_version,
        DISCRETIONARY_MINUTES: verdict.discretionary_minutes,
        SHORTFALLS: [_stored_shortfall(one) for one in verdict.shortfalls],
        TRADEOFFS: [_stored_tradeoff(one) for one in verdict.tradeoffs],
    }


def verdict_of(document: JsonDocument) -> Verdict:
    """The verdict a stored document names, rebuilt through the domain's own constructor."""
    return rebuilt(
        lambda: Verdict(
            feasible=read_flag(document.get(FEASIBLE), field=FEASIBLE),
            provenance=read_member(Provenance, document.get(PROVENANCE), field=PROVENANCE),
            computed_at=read_instant(document.get(COMPUTED_AT), field=COMPUTED_AT),
            input_version=read_whole_number(document.get(INPUT_VERSION), field=INPUT_VERSION),
            discretionary_minutes=read_whole_number(
                document.get(DISCRETIONARY_MINUTES), field=DISCRETIONARY_MINUTES
            ),
            shortfalls=tuple(
                _shortfall_of(read_mapping(one, field=SHORTFALLS))
                for one in read_list(document.get(SHORTFALLS), field=SHORTFALLS)
            ),
            tradeoffs=tuple(
                _tradeoff_of(read_mapping(one, field=TRADEOFFS))
                for one in read_list(document.get(TRADEOFFS), field=TRADEOFFS)
            ),
        ),
        field="verdict",
    )


def _stored_shortfall(shortfall: Shortfall) -> JsonObject:
    return {
        "kind": shortfall.kind.value,
        "minutes": shortfall.minutes,
        "against": list(shortfall.against),
        "honoring": list(shortfall.honoring),
        "deadline": None if shortfall.deadline is None else stored_instant(shortfall.deadline),
        "areaId": None if shortfall.area_id is None else stored_id(shortfall.area_id),
    }


def _shortfall_of(stored: JsonDocument) -> Shortfall:
    return Shortfall(
        kind=read_member(ShortfallKind, stored.get("kind"), field="kind"),
        minutes=read_whole_number(stored.get("minutes"), field="minutes"),
        against=_names(stored.get("against"), field="against"),
        honoring=_names(stored.get("honoring"), field="honoring"),
        deadline=read_optional_instant(stored.get("deadline"), field="deadline"),
        area_id=read_optional_id(stored.get("areaId"), field="areaId"),
    )


def _stored_tradeoff(tradeoff: Tradeoff) -> JsonObject:
    return {
        "kind": tradeoff.kind.value,
        "label": tradeoff.label,
        "targetId": stored_id(tradeoff.target_id),
        "deltaMinutes": tradeoff.delta_minutes,
    }


def _tradeoff_of(stored: JsonDocument) -> Tradeoff:
    return Tradeoff(
        kind=read_member(AdjustmentKind, stored.get("kind"), field="kind"),
        label=read_text(stored.get("label"), field="label"),
        target_id=read_id(stored.get("targetId"), field="targetId"),
        delta_minutes=read_optional_whole_number(stored.get("deltaMinutes"), field="deltaMinutes"),
    )


def _names(value: object, *, field: str) -> tuple[str, ...]:
    """A rendered list of reasons, each of which has to be readable text."""
    return tuple(read_text(one, field=field) for one in read_list(value, field=field))
