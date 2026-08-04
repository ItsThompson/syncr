"""Day shapes: the three concepts that end repeat authoring, and no fourth.

A **day type** names a kind of day. A **template** is the shape of one day type and holds ordered
entries. A **week pattern** says which day type each of the seven weekdays uses. Declared once,
materialized every week.

An entry is either **concrete**, naming a specific routine or habit at a target time, or a
**slot**, naming an Area and a duration with the content bound late. Late binding itself belongs
to the solver: what this package ships is the declaration and the invariants that keep the model
from growing a fourth concept.

**There are no template periods.** An earlier model had daily, weekly, and monthly ones. Weekly
and monthly recurrence is already ``Habit.cadence``, so separate periods would have needed
composition and override rules for no added expressiveness. Three concepts replace three
template periods, and no request shape in this package accepts a cadence.

**A template entry is fixed by derivation, not pinned.** Its time comes from the shape, so the
solver may not move it, it renders no pin glyph, and it creates no ``Pin`` row. That is a
structural fact rather than a user act, which is why it is not a training label. Fixed by
derivation means never moved SILENTLY, not never moved: an anchor landing on a materialized entry
raises a conflict, and the user may still move one by editing the shape or by pinning that single
occurrence.

The consequence worth keeping in mind: because entries and anchors are fixed, the solver's search
space is narrow. It binds content into fixed-time slots and places cadence items into leftover
gaps. It does not arrange the day.

Import layout, so a reader knows where to look:

| Module | Holds |
|---|---|
| ``config.py`` | the table names, the route paths, and the two name bounds |
| ``models.py`` | the four tables and the constraints the database itself holds |
| ``records.py`` | the frozen views the repositories return |
| ``repository.py`` | tenant-scoped persistence for shapes, entries, and the pattern |
| ``declarations.py`` | what a request asked to declare or change, per kind of entry |
| ``rules.py`` | what a declaration must satisfy, and how a refusal reaches the caller |
| ``invalidation.py`` | which weeks a mutation invalidates, and the one rule that decides |
| ``schemas.py`` | the day-type, shape, and pattern wire shapes |
| ``entry_schemas.py`` | the wire shapes one entry is declared in, as a discriminated union |
| ``service.py`` | authorization, the ordering of reads and writes, and the bump |
| ``api.py`` | the twelve routes |

Materializing these declarations into a week is NOT here. The week assembler resolves each date's
weekday to a day type, the day type to a shape, and the shape's entries to placements, and the
identity a materialized entry takes belongs to the plan's value types.
"""
