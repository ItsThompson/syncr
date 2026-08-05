"""The words a tradeoff is offered in. One phrase per kind, and no arithmetic.

Separated from the enumeration for the reason ``syncr_domain.feasibility.honoring`` is separated
from the probe: the enumeration decides what could close a gap and by how much, and this decides
what the user reads. Nothing here can change what is offered or what it recovers.

Durations render through the domain's own ``hours_and_minutes``, because the same figure appears
in a shortfall's honored constraint and in the label of the tradeoff offered against it, and two
renderings of one figure is how a panel comes to disagree with itself.

**A target is named in the user's own words**, which is the routine's title, the task's title, or
the Area's name as they declared it. Nothing is re-cased or abbreviated: the spec's example label
lowercases a routine a user capitalized, and following the example rather than the declaration
would put a word on the panel the user never typed.

**The nights are named, because a routine reduction stores the dates it touched.** The weekday
names are a tuple indexed by ``date.weekday()`` rather than ``strftime("%a")``, which reads the
process locale: a label is part of the product's wording and must not change with an environment
variable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from syncr_domain.feasibility import hours_and_minutes

if TYPE_CHECKING:
    from collections.abc import Sequence

    from syncr_domain.zones import Date

# Indexed by `date.weekday()`, Monday first, in the abbreviation the design language's gutter
# uses. Locale-independent by construction.
WEEKDAY_NAMES: Final = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def dropped(*, title: str) -> str:
    """``Drop Kim's Game Project this week``."""
    return f"Drop {title} this week"


def partial_accepted(*, title: str) -> str:
    """``Accept partial delivery on F&F Past Papers``."""
    return f"Accept partial delivery on {title}"


def floor_breached(*, name: str, minutes: int) -> str:
    """``Breach the Fitness floor by 1h20m``."""
    return f"Breach the {name} floor by {hours_and_minutes(minutes)}"


def routine_reduced(*, title: str, minutes_each: int, nights: Sequence[Date]) -> str:
    """``Reduce Sleep by 20m on Tue, Wed and Thu``.

    One figure and a list of nights rather than a total, because the reduction is per night and
    the user is being asked about each of them. The total is on the tradeoff as the minutes it
    recovers.
    """
    return f"Reduce {title} by {hours_and_minutes(minutes_each)} on {nights_named(nights)}"


def nights_named(nights: Sequence[Date]) -> str:
    """``Tue``, ``Tue and Wed``, ``Tue, Wed and Thu``.

    No serial comma before the ``and``, which is the wording every other list in the product
    uses.
    """
    named = [WEEKDAY_NAMES[night.weekday()] for night in nights]
    if len(named) <= 1:
        return "".join(named)
    return f"{', '.join(named[:-1])} and {named[-1]}"
