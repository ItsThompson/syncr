"""One Area's figures for one week: two floors, a gross target, and what is already placed.

The two floor quantities are the pair this module exists to keep apart, and the argument is the
same shape as the two task quantities in ``demand.py``.

```
                       floor_minutes                floor_reservation_minutes
reader                 the SOLVER, checking a floor the PROBE, via for_probe()
nets                   IMMOVABLE placements only    EVERY placement in the Area
```

**Merged into one field, the probe reports a floor shortfall on the normal healthy state of the
product.** A healthy solved week is by definition one whose floors are met by solver-placed
blocks, and solver-placed blocks are unpinned. With a Fitness floor of 5h fully met by unpinned
blocks and 2h of genuinely uncommitted capacity left, an immovable-only reservation reads 5h
against 2h of free capacity and reports a 3h gap that does not exist.

**Netted the other way, the solver under-places the floor.** The floor is checked against a plan
the solver is still building, so its reservation has to cover everything the solver can still
place. Reserving against a block the solver is about to discard would let it place the floor short
by whatever the previous solve happened to place.

One consequence of the split is worth stating, because it reads as asymmetric and is not.
Pinning an already-placed block leaves the reservation UNCHANGED, which is what stops a pin
improving a verdict, and it LOWERS ``floor_minutes`` by the pinned block's minutes, which is
correct: the solver now has that much less to place in order to honour the floor.

``target_minutes`` nets nothing, because it is a reporting figure rather than a reservation.
``placed_minutes`` names its own set, which is the reservation's, so the ``floor`` reason clause
cannot disagree with whichever reservation a reader compares it against.

The Area's **name** travels with the figures for one reason: the probe renders a shortfall that says
what cannot be satisfied in the user's words, and it resolves no identifier because it performs no
lookup at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_domain.budgets import minutes_after_floors, target_minutes
from syncr_solver.inputs import AreaBudget

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_api.areas.records import AreaRecord
    from syncr_api.plans.netting import PlacedTime
    from syncr_domain.identifiers import AreaId


def area_budgets(
    areas: Sequence[AreaRecord],
    *,
    discretionary_minutes: int,
    placed: PlacedTime,
    caps: Mapping[AreaId, int | None],
) -> tuple[AreaBudget, ...]:
    """Every declared Area's figures for this week, in the Areas' own order.

    ``discretionary_minutes`` is the week's denominator, which is what the proportional share of
    the remainder is taken from. It arrives computed rather than derived here, so the target an
    Area reads here and the target the budget report renders are the same arithmetic over the
    same denominator.

    ``caps`` carries each Area's own daily ceiling. It is a parameter rather than a read of the
    preference rows, because a cap is an Area preference and an override may not carry one: the
    resolution that enforces that is stated once, where preferences resolve.
    """
    shares = [area.as_share() for area in areas]
    names = {area.id: area.name for area in areas}
    after_floors = minutes_after_floors(discretionary_minutes, shares)
    return tuple(
        AreaBudget(
            area_id=share.area_id,
            name=names[share.area_id],
            floor_minutes=max(
                0, share.floor_minutes - placed.immovable_minutes_of_area(share.area_id)
            ),
            floor_reservation_minutes=max(
                0, share.floor_minutes - placed.minutes_of_area(share.area_id)
            ),
            target_minutes=target_minutes(share, after_floors=after_floors),
            placed_minutes=placed.minutes_of_area(share.area_id),
            max_per_day_minutes=caps.get(share.area_id),
        )
        for share in shares
    )
