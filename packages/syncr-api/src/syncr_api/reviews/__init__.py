"""The pie review: what a quarter of confirmed behaviour says, and the revision it proposes.

A review is a MODE of the Areas screen rather than a destination, and this package is the payload
that mode reads. It answers four questions about one quarter: what the composition of the time was,
how it trended week by week, how far each Area landed from its target, and what shares the behaviour
suggests declaring instead.

Every module in this package appears in the table below.

| Module | Holds |
|---|---|
| ``config.py`` | the two route paths, the period parameter, and the quarter's width |
| ``coverage.py`` | what a confirmed day gives an Area, and how a day is classified |
| ``history.py`` | the reviewed quarter, read from the plan of record and the outcome log |
| ``figures.py`` | one week's four figures, stated once for its three consumers |
| ``proposals.py`` | which weeks are evidence, and the revision they propose |
| ``readings.py`` | the whole review, assembled |
| ``statements.py`` | what the review says in words |
| ``declarations.py`` | the shares one apply asked to declare |
| ``rules.py`` | how an apply is refused |
| ``schemas.py`` | the wire shapes |
| ``service.py`` | authorization, the read, and the one write |
| ``api.py`` | the two routes |
| ``injection.py`` | the one place its collaborators are composed, scoped to a tenant |
| ``wiring.py`` | the router the app factory asks for |

**This package owns no table.** It reads plan storage's revisions and outcome log, `offplan`'s
periods, and `areas`' declarations, and it writes exactly one column: an Area's ``budget_percent``,
and only when the user applies a revision.

**Three rules separate this from the budget report**, which is `syncr_api.budgets`. That report
answers what a week PLANS to give each Area, over a recomputed denominator. This answers what each
Area actually GOT, over the plan of record's own stored denominator, from confirmed days only, with
off-plan spans excluded entirely. `coverage.py` and `history.py` each state their half of that.

**syncr never re-cuts the budget on its own.** The read proposes and writes nothing at all; the
apply writes only what a request named. That is US-REV-03, and it is why the proposal and the
application are two routes rather than one job.
"""
