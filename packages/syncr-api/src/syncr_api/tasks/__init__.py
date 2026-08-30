"""The backlog: tasks, their physics, and the six routes that capture, settle, and reopen them.

A task is one piece of work the user wants scheduled. Roughly a quarter of the blocks in the
reference weeks are task work; the rest are routines, habits, and anchors, which is why a task is
one of three kinds of intent rather than the only one.

**The physics is the substance of this module.** An estimate, a minimum chunk, and an atomicity
flag are what stop fill placement putting fifteen minutes of something that needs an hour to start
into whatever gap it finds. The rules over those numbers are arithmetic, so they live in
``syncr_domain.tasks`` and are only mapped to statuses here.

**A task carries no preferred time.** Preferred times are a ``Preference``, whose owner is an
Area, a Habit, or a Task, so a task inherits its Area's windows unless it overrides them. No
column, no request field, and no response field here could hold one.

**At-risk marking is not computed here.** A task is at risk when the feasibility probe reports a
``deadline_capacity`` shortfall naming it, so the backlog reads the verdict's shortfalls rather
than comparing a deadline against a capacity of its own: two comparisons would put a task at risk
on one screen and fine on another. The header's ``atRiskCount`` is present and zero
wires it once the probe exists.

Import layout, so a reader knows where to look:

| Module | Holds |
|---|---|
| ``config.py`` | the bounds, the table name, and the route paths |
| ``models.py`` | the one table |
| ``records.py`` | the frozen view the repository returns, and the two derived figures |
| ``declarations.py`` | what a request asked to capture or change, three-valued per field |
| ``rules.py`` | the two stored-row comparisons, and the map from a domain rejection to a status |
| ``schemas.py`` | the wire shapes |
| ``repository.py`` | tenant-scoped persistence, including the count the header states |
| ``service.py`` | authorization, the physics, the Area checks, and the solve-input bump |
| ``api.py`` | the six routes |
"""
