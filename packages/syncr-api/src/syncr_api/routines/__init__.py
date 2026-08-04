"""Routines: the circadian frame, and the sleep floor's one home.

A routine is a SPAN, not a marker. ``Sleep 23:00 + 8h`` is what bounds a day, and subtracting
the frame is what makes discretionary time computable at all, so a routine without a duration is
refused rather than defaulted.

Three properties separate a routine from everything else the week holds:

**It carries no Area and therefore no pigment.** It defines how much time exists rather than
competing for it, so it never appears in Area budget arithmetic and it renders with the frame
wash.

**Its target time is local.** ``Wake 05:00`` means 05:00 wherever the user is, resolved per day
against the active zone, which is why the column holds wall time rather than an instant.

**Its floor is the sleep floor.** ``min_duration_minutes`` is how far a routine may be
compressed, it defaults to the target duration, and on the sleep routine it is the negotiable
resource the solver may propose spending and may never spend silently. There is no
sleep-specific rule anywhere and no settings field for the floor: sleep is simply the routine
users give an elastic range to.

Import layout, so a reader knows where to look:

| Module | Holds |
|---|---|
| ``config.py`` | the table name, the route paths, and the title bound |
| ``models.py`` | the one table, and the Area column it deliberately lacks |
| ``records.py`` | the frozen view the repository returns |
| ``repository.py`` | tenant-scoped persistence |
| ``declarations.py`` | what a request asked to declare or change, and the inelastic default |
| ``rules.py`` | how a span the domain refused becomes a stated 422 |
| ``schemas.py`` | the wire shapes |
| ``service.py`` | authorization, the refused span, and the solve-input bump |
| ``api.py`` | the five routes |

The frame's arithmetic is NOT here. A span's invariants, its elasticity predicate, and how a
target time becomes an interval on a date all live in ``syncr_domain.routines``, so the solver,
the assembler, and this module read one implementation. The effective duration of one
occurrence, and its clamp to the floor, belong to the week assembler.
"""
