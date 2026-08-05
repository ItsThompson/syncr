"""Feasibility: the synchronous capacity probe, its inputs, and the verdict it returns.

**Every module in this package appears in the table below**, which a test asserts against the
directory, because an index a reader cannot trust is worse than none.

| Module | Holds |
|---|---|
| ``inputs.py`` | ``ProbeInputs`` and its member types, with the question each field answers |
| ``verdict.py`` | ``Verdict``, ``Shortfall``, the four shortfall kinds, and the duration wording |
| ``probe.py`` | the arithmetic: two spans, one free-capacity set, three checks, one discount |
| ``honoring.py`` | the words a shortfall names its honored constraints in, one of them shared |
| ``errors.py`` | the one rejection this vocabulary raises |

The names below are the package's surface, so a caller writes ``from syncr_domain.feasibility
import probe`` rather than reaching into a module. Nothing else here is public.
"""

from __future__ import annotations

from syncr_domain.feasibility.errors import FeasibilityError
from syncr_domain.feasibility.honoring import floor_honored
from syncr_domain.feasibility.inputs import (
    DeadlineDemand,
    FloorReservation,
    ProbeInputs,
    ScopedWindow,
)
from syncr_domain.feasibility.probe import probe
from syncr_domain.feasibility.verdict import (
    Provenance,
    Shortfall,
    ShortfallKind,
    Tradeoff,
    Verdict,
    hours_and_minutes,
    minimum_chunk_shortfall,
)

__all__ = [
    "DeadlineDemand",
    "FeasibilityError",
    "FloorReservation",
    "ProbeInputs",
    "Provenance",
    "ScopedWindow",
    "Shortfall",
    "ShortfallKind",
    "Tradeoff",
    "Verdict",
    "floor_honored",
    "hours_and_minutes",
    "minimum_chunk_shortfall",
    "probe",
]
