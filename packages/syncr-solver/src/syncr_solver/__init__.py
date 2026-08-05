"""syncr placement. Depends on syncr-domain. Zero ML dependencies.

One entry point is public today: :func:`~syncr_solver.materialize.materialize`, which places what
derivation determines. ``solve`` is the second and lands in a later slice, and it calls the first as
its own phase one. Everything else here is machinery those two are composed from, including
``derive``, which is ``materialize`` plus the refusals a solve carries into its log.

**Every module in this package appears in the index below**, which a test asserts against the
directory in both directions, because an index a reader cannot trust is worse than none.

| Module | Holds |
|---|---|
| ``inputs.py`` | ``SolveInputs`` and its member types: everything a solve reads, resolved |
| ``materialize.py`` | the entry point, what is placed unchecked, and the order candidates take |
| ``derivation.py`` | one block per determined placement, and one empty slot per Area slot |
| ``clauses.py`` | the ``bound`` clause a derived block carries, and the labels it renders |
| ``constraints.py`` | the hard-constraint vocabulary, the table, the state, and the checker |
| ``occupancy.py`` | the four rules a plan derived from nothing else can break |
| ``figures.py`` | the minute figures a document carries, over the inputs and the blocks |
| ``metrics.py`` | the families this package publishes, on the shared registry |
| ``errors.py`` | what a malformed resolved input is refused with |

The zero-ML rule is the load-bearing one: no language model sits in the placement loop and no ML
library is a dependency, which is what keeps the api image free of scipy, the solver testable
against literals, and ``syncr-learning`` replaceable without touching the request path.
"""

from syncr_solver.materialize import materialize
from syncr_solver.metrics import MaterializeCause

__all__ = ["MaterializeCause", "materialize"]
