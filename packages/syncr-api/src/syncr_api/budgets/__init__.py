"""The budget report: one period's discretionary time, and how the Areas divide it.

This package owns no table. It resolves a week's real span, reads the Areas' declarations, asks
what the week already holds, and hands all of it to the domain's budget arithmetic, which has
exactly one implementation shared with the feasibility probe and the solver's capacity check.

Import layout, so a reader knows where to look:

| Module | Holds |
|---|---|
| ``config.py`` | the route path and the period parameter |
| ``occupancy.py`` | the five sets a week holds, and who is asked for them |
| ``schemas.py`` | the wire shape |
| ``service.py`` | authorization, the span, and the one call into the arithmetic |
| ``api.py`` | the one route |

Separate from ``syncr_api.areas`` because it is a report rather than a resource: the Areas
module owns two tables and eight routes over them, and this owns one read that divides a
denominator neither table stores.
"""
