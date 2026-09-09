"""A failed solve's inputs, as the document the operation retains so the failure reproduces.

``Operation.failed_input_snapshot`` exists so a production failure can be reproduced locally: load
the document and call the solver. ``input_version`` cannot do that job -- it is a counter, so
re-assembling against it yields current state rather than the state that failed.

**The encoder is derived from the value rather than written per field, and that is the point.**
``SolveInputs`` holds a field per resolved quantity over member types that each carry their own
invariants, and a hand-written encoder would silently drop a field added later: the write would
still succeed and the snapshot would still look complete. Walking the dataclass instead means a new
field is in the document the day it is on the value. The figures are deliberately absent: a count
stated here is one nobody re-derives, and ``dataclasses.fields`` is what the reader inventories
against.

**So the only hand-written part is the leaf table, and an unknown leaf RAISES.** That is the whole
guard: without it an unrecognised type would reach ``json`` as its ``repr``, which reproduces
nothing and cannot be detected by reading the document. The refusal names the type, so the fix is
to add a leaf rather than to discover a corrupt snapshot months later.

**A plan is named before the walk, because it has a stored form of its own that the walk cannot
produce.** A reason clause is a Python type in the domain and an object in a document, so a stored
plan carries a discriminator saying which of the six kinds each clause is, and the value itself
carries none: walked generically, a clause stores its fields with nothing to say what it is and no
reader can rebuild it. So both plans a snapshot holds go through the document codec, which is the
same direction ``plan_revisions.document`` is written in.

**Written on failure only, and bounded to one week.** It is pruned with the operation at ninety
days.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Final
from uuid import UUID

from syncr_api.plans.stored_documents import stored_document
from syncr_domain.intervals import Interval
from syncr_domain.plan import PlanDocument
from syncr_domain.weeks import IsoWeek

if TYPE_CHECKING:
    from syncr_api.core.columns import JsonObject
    from syncr_solver.inputs import SolveInputs

# What the document names the encoded value, so a reader knows what shape to expect before it
# starts. Bumped when the walk changes shape rather than when a field is added, because a reader
# that walks the same way needs no warning about a new key.
SNAPSHOT_FORM: Final = 4
FORM = "form"
INPUTS = "inputs"


def as_snapshot(inputs: SolveInputs) -> JsonObject:
    """The resolved inputs one solve read, as the document its operation retains."""
    return {FORM: SNAPSHOT_FORM, INPUTS: _encoded(inputs)}


class UnencodableInput(Exception):
    """A value the snapshot walk holds no leaf form for, so encoding it would lose it."""


def _encoded(value: object) -> object:
    """One value, as JSON, walking a dataclass and refusing a leaf this module does not name."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Interval):
        # Named before the dataclass walk because a span reads far better as a pair of instants
        # than as two nested objects, and both halves are already leaves.
        return {"start": _encoded(value.start), "end": _encoded(value.end)}
    if isinstance(value, IsoWeek):
        # Before the walk for the same reason: the week has one canonical spelling and its two
        # fields would otherwise be written as a pair nothing else in the tree reads.
        return str(value)
    if isinstance(value, PlanDocument):
        # Before the walk because a plan's stored form is not derivable from the value: the walk
        # cannot write the clause discriminator a document carries, so a plan it walked would
        # store reason clauses no reader can tell apart.
        return stored_document(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _encoded(getattr(value, field.name)) for field in dataclasses.fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(_encoded(key)): _encoded(held) for key, held in value.items()}
    if isinstance(value, list | tuple | frozenset | set):
        return [_encoded(held) for held in value]
    raise UnencodableInput(
        f"a solve input holds a {type(value).__name__}, which this snapshot has no form for: "
        "encoding it as text would produce a document that reproduces nothing, so the walk "
        "refuses rather than writing something a reader cannot rebuild"
    )
