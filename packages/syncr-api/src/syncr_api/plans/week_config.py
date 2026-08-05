"""The paths and the resource name the week routes read.

Beside ``config.py`` rather than inside it, because that module states the vocabularies the
plan-side TABLES are defined against and these are the identifiers a request carries. The
calendar package keeps the same separation between ``config.py`` and ``google_config.py``.

**The prefix and the week's field name are the concession module's**, not restated here. Seven
routes hang off one week and three of them shipped first, so the spelling of the path parameter
and the field a refusal names are read from where they were settled: a second statement of
either is how the seven routes would come to have two shapes for one parameter.

``/{iso_week}`` is snake_cased, as every path parameter this api declares is. Section 13's route
table writes ``{isoWeek}``, which is the same URL with a different parameter NAME, and the
generated client reads the name.
"""

from __future__ import annotations

from typing import Final

# Relative to the router's own prefix, which is the week collection the concession routes
# already hang off.
WEEK_PATH: Final = "/{iso_week}"
REVISIONS_PATH: Final = "/{iso_week}/revisions"
SOLVE_PATH: Final = "/{iso_week}/solve"
VERDICT_PATH: Final = "/{iso_week}/verdict"

# The query parameter that bypasses the debounce window a solve would otherwise wait out. The
# window is the coordinator's, and so is the reading of this flag once it exists.
IMMEDIATE_PARAMETER: Final = "immediate"

WEEK_RESOURCE: Final = "week"
