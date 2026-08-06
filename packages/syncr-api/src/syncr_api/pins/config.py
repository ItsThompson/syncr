"""The paths, the route names, and the resource word the pin routes read.

The prefix and the week's field name are the concession module's, not restated here: three pin
routes hang off the same week collection the verdict, the solve and the tradeoff routes do, so the
spelling of the path parameter and the field a refusal names are read from where they were settled.

``/{iso_week}`` is snake_cased, as every path parameter this api declares is. Section 13's route
table writes ``{isoWeek}``, which is the same URL with a different parameter NAME, and the generated
client reads the name.

The three route names are what the idempotency guard stores a response against. They are per route
rather than per feature, so a key reused across two of them is refused as a reused key rather than
replaying the wrong answer.
"""

from __future__ import annotations

from typing import Final

# Relative to the router's own prefix, which is the week collection.
PINS_PATH: Final = "/{iso_week}/pins"
PIN_PATH: Final = "/{iso_week}/pins/{pin_id}"
REJECT_BLOCK_PATH: Final = "/{iso_week}/reject-block"

PIN_ROUTE: Final = "pins.create_pin"
UNPIN_ROUTE: Final = "pins.remove_pin"
REJECT_BLOCK_ROUTE: Final = "pins.reject_block"

PIN_RESOURCE: Final = "pin"
BLOCK_RESOURCE: Final = "block"

# The field a refusal names when the request's own placement is what was wrong: a start already
# gone, or one outside the week. A refusal about the BLOCK the request names is a fact about stored
# state rather than about a field, so it carries no field error at all.
START_FIELD: Final = "start"
