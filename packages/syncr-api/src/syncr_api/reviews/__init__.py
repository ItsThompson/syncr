"""The two reviews: what a quarter of confirmed behaviour says, and what one week's session raises.

A review is a MODE of an existing screen rather than a destination, and this package is the payload
each mode reads. The pie review is a mode of the Areas screen and answers four questions about one
quarter: what the composition of the time was, how it trended week by week, how far each Area landed
from its target, and what shares the behaviour suggests declaring instead. The weekly session is a
mode of the Week screen and answers one: what happened last week, and what to know before approving
next week.

Every module in this package appears in the table below.

| Module | Holds |
|---|---|
| ``config.py`` | the three route paths, the parameters, and the windows each review reads |
| ``coverage.py`` | what a confirmed day gives an Area, and how a day is classified |
| ``history.py`` | the reviewed weeks, read from the plan of record and the outcome log |
| ``figures.py`` | one week's four figures, stated once for its three consumers |
| ``proposals.py`` | which weeks are evidence, and the revision they propose |
| ``readings.py`` | the pie review, assembled |
| ``naming.py`` | the words every raise shares: what to call a thing, how to state a count |
| ``skips.py`` | the run of weeks in which one item was proposed and skipped, and its raise |
| ``collisions.py`` | one commitment meeting one block week after week, and its raise |
| ``raised.py`` | the raised item, and the five kinds the week view alone gives |
| ``session_sources.py`` | the six reads the session takes beyond the week view |
| ``session.py`` | the session's reading, and the composers that build it |
| ``statements.py`` | what a review says in words |
| ``declarations.py`` | the shares one apply asked to declare |
| ``rules.py`` | how an apply is refused |
| ``schemas.py`` | the pie review's wire shapes |
| ``session_schemas.py`` | the weekly session's wire shapes |
| ``service.py`` | authorization, the two reads, and the one write |
| ``api.py`` | the three routes |
| ``injection.py`` | the one place their collaborators are composed, scoped to a tenant |
| ``wiring.py`` | the router the app factory asks for |

**This package owns no table.** It reads plan storage's revisions, outcome log, conflicts and pins,
`offplan`'s periods, `anchors`' commitments, `tasks`' backlog, `habits`' declarations, and `areas`'
own, and it writes exactly one column: an Area's ``budget_percent``, and only when the user applies
a revision.

**Both reads write nothing at all**, including no ``VerdictEvent``. No read path records the
transition it observes, and the session's payload carries a verdict, so it is covered by the guard
stated over the response shapes that declare that field.

**Three rules separate this from the budget report**, which is `syncr_api.budgets`. That report
answers what a week PLANS to give each Area, over a recomputed denominator. This answers what each
Area actually GOT, over the plan of record's own stored denominator, from confirmed days only, with
off-plan spans excluded entirely. `coverage.py` and `history.py` each state their half of that.

**syncr never re-cuts the budget on its own, and it never quietly deprioritizes anything either.**
The pie review's read proposes and writes nothing; its apply writes only what a request named. The
session raises a chronically skipped item and changes neither its priority nor its presence, and it
renders a promotion candidate without applying one. Those are US-REV-03, US-REV-02 and US-TPL-05,
and they are why every proposal here is a separate route from its application.
"""
