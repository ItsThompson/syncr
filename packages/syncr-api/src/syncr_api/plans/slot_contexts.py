"""What a wording about an empty slot may name besides its reason: the Area's own name.

A stored plan holds an Area identifier per empty slot and no name, and that is deliberate: a name is
the user's own word for an Area they may rename at any time, and a week already approved must not
change what it says when they do. So the name is resolved where a response is composed, against the
Areas that response was read with.

**One read of the Areas answers every slot.** The names arrive as a mapping the caller already
holds rather than as a repository this module reads, so a week holding many gaps costs the same read
as a week holding one.

A slot whose Area the mapping does not name is refused rather than resolved to a blank.
:class:`syncr_domain.gaps.SlotContext` holds a name rather than an optional one, so there is nothing
truthful to put in its place, and the two sides come from one transaction over a table no route
removes a row from: a slot the names do not cover means the plan and the Areas disagree about which
Areas this tenant has. That last premise is held by
``tests/test_areas_refusal_sentence.py``, which reads the route table off the built app, so the
engineer who adds a route removing an Area is told that this resolution rests on there being none.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.plans.errors import SlotContextRejected
from syncr_domain.gaps import SlotContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from syncr_domain.gaps import EmptySlot
    from syncr_domain.identifiers import AreaId


def slot_context(slot: EmptySlot, area_names: Mapping[AreaId, str]) -> SlotContext:
    """What this slot's Area is called, in the form a gutter label resolves names from."""
    name = area_names.get(slot.area_id)
    if name is None:
        raise SlotContextRejected(
            f"the empty slot at {slot.interval.start.isoformat()} is charged to Area "
            f"{slot.area_id}, which is not among the {len(area_names)} this read named: what an "
            "unfilled slot is offered for is stated in terms of its Area, so a plan naming one "
            "the Areas do not is refused rather than answered"
        )
    return SlotContext(area_name=name)
