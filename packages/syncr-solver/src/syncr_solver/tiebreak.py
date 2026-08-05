"""The order candidates are offered in: one total order, ending in an identity.

The solver is deterministic, which means every iteration order it takes is derived from a
comparator rather than from a dictionary, a set, or the order an input list happened to arrive
in. This is that comparator, and its last term exists purely so that no tie can fall through to
whatever the runtime happened to do.

## The four terms, and what each answers

```
1. largest absolute floor shortfall in the candidate's Area   what the week owes most
2. earliest deadline                                          what runs out of time first
3. longest staleness                                          what has fallen behind
4. the Area, then the content identity                        the term that makes it total
```

The first three are the product's own priorities. The fourth is arithmetic: without it two
candidates equal on every meaningful axis would be ordered by their arrival, and the same inputs
could produce two different plans.

**The fourth term reads the whole binding rather than the entity identifier alone.** The design
names "``area_id``, then entity id", and an entity id is not total over candidates: a habit's four
occurrences in one week share one, and a task's chunks share one as well. So the key ends in the
occurrence key and the chunk number, which are exactly the components that separate several
candidates of one entity.

## One definition, read two ways

:func:`compare` and :func:`in_tiebreak_order` both read :func:`order_key`, so the comparator and
the sort cannot disagree about which of two candidates comes first. A second expression of the
order is how a comparator comes to answer one thing and a sort another.

## No seed reaches this

``SolveInputs.seed`` exists so that a tie a comparator cannot break is resolved reproducibly. This
comparator breaks every tie, so nothing here reads the seed and no figure a document carries can
depend on one.
"""

from __future__ import annotations

# A sentinel instant for a candidate with no deadline, so the key stays one shape. `datetime.max`
# rather than a large literal, because the value must sort after every deadline a week can carry
# and there is no other total answer.
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final
from uuid import UUID

if TYPE_CHECKING:
    from syncr_domain.identifiers import AreaId
    from syncr_domain.intervals import Instant
    from syncr_solver.candidates import Candidate

_NO_DEADLINE: Final = datetime.max.replace(tzinfo=UTC)

# What a candidate carrying no chunk number sorts as. Below zero, so an undivided demand orders
# ahead of the chunks of a divided one rather than tying with the first of them.
_NO_CHUNK: Final = -1

type OrderKey = tuple[int, Instant, int, AreaId, UUID, str, int]
"""The key the order is taken over: three priorities, then the identity that makes it total."""


def order_key(candidate: Candidate) -> OrderKey:
    """This candidate's position in the total order, ascending.

    The two descending terms are negated rather than sorted in reverse, so one ascending sort
    expresses all four and no caller has to reverse part of a key.
    """
    return (
        -candidate.floor_shortfall_minutes,
        candidate.deadline or _NO_DEADLINE,
        -candidate.stale_minutes,
        candidate.area_id,
        candidate.binding.entity_id,
        candidate.binding.occurrence_key,
        candidate.binding.split_index if candidate.binding.split_index is not None else _NO_CHUNK,
    )


def compare(a: Candidate, b: Candidate) -> int:
    """Negative when ``a`` is offered first, positive when ``b`` is, and zero only for one demand.

    Zero means the two candidates name the same content instance, because the key ends in the
    whole of a binding. So a caller may read a zero as "these are one candidate" rather than as
    "the order is undecided", which is the property the final term buys.
    """
    left, right = order_key(a), order_key(b)
    return (left > right) - (left < right)


def in_tiebreak_order(candidates: tuple[Candidate, ...]) -> tuple[Candidate, ...]:
    """These candidates in the order they are offered. The one sort the construction takes."""
    return tuple(sorted(candidates, key=order_key))
