"""The path, the route name, and the words a refusal names.

The prefix and the week's field name are the concession module's, not restated here: the approve
route hangs off the same week collection the view, the history, the solve, the pins and the
tradeoff routes do, so the spelling of the path parameter and the field a refusal names are read
from where they were settled.

``/{iso_week}`` is snake_cased, as every path parameter this api declares is. The route table's
table writes ``{isoWeek}``, which is the same URL with a different parameter NAME, and the
generated client reads the name.

The route name is what the idempotency guard stores a response against. It is per route rather
than per feature, so a key reused across two routes is refused as a reused key rather than
replaying another route's answer.

There is no resource word here. Every other feature's refusals name the resource they could not
find (``No pin of that week matches that identifier``), and this route's refusals are about the
week's own state rather than about a thing a caller named, so each states what happened instead.
"""

from __future__ import annotations

from typing import Final

# Relative to the router's own prefix, which is the week collection.
APPROVE_PATH: Final = "/{iso_week}/approve"

APPROVE_ROUTE: Final = "approvals.approve_week"
