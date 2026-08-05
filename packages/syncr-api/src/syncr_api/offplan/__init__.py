"""Off-plan periods: the spans a user declares off, and the fourth thing the denominator
subtracts.

A period is an arbitrary half-open interval with instant precision, snapped to the quarter hour,
so a long weekend and a fortnight are one concept and Friday 14:00 to Monday 09:00 is one
record. It is not an off-plan MODE: there are no off-plan scheduling rules, no off-plan glyph,
and no off-plan affordance for keeping one thing anyway. The span extends the existing
discretionary-time formula, renders as an ordinary forbidden window, and a pin inside it is an
ordinary pin.

Import layout, so a reader knows where to look:

| Module | Holds |
|---|---|
| ``config.py`` | the bounds, the table name, and the route paths |
| ``models.py`` | the one table |
| ``records.py`` | the frozen view the repository returns |
| ``repository.py`` | tenant-scoped persistence, including the unclipped ``for_span`` read |
| ``declarations.py`` | what a request asked to declare or change, three-valued per field |
| ``rules.py`` | the status each domain rejection carries |
| ``weeks.py`` | which ISO weeks a span touches, and therefore what a mutation invalidates |
| ``segments.py`` | the local day segments a span holds, which is what the projection writes |
| ``occupancy.py`` | the spans a week holds, as the budget report asks for them |
| ``reading.py`` | how many off-plan minutes a week had, and whether to say why |
| ``schemas.py`` | the wire shapes |
| ``service.py`` | authorization, the two invariants, and the version bump |
| ``api.py`` | the four routes |

The invariants are NOT here. ``syncr_domain.off_plan`` owns the grid rule and the non-overlap
rule, and ``syncr_domain.discretionary`` owns the union that keeps a frame span inside an
off-plan span from being subtracted twice. This package stores periods, answers for them over
HTTP, and hands them to those two.
"""
