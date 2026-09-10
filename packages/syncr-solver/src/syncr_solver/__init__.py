"""syncr placement. Depends on syncr-domain. Zero ML dependencies.

Two entry points are public: :func:`~syncr_solver.materialize.materialize`, which places what
derivation determines, and :func:`~syncr_solver.solve.solve`, which binds content, packs the rest,
improves the result by bounded local search, and answers with an authoritative verdict. The second
calls the first as its own phase one. Everything else here is machinery those two are composed
from, including ``derive``, which is ``materialize`` plus the refusals a solve carries into its log.

**Every module in this package appears in the index below**, which a test asserts against the
directory in both directions, because an index a reader cannot trust is worse than none.

| Module | Holds |
|---|---|
| ``inputs.py`` | ``SolveInputs`` and its member types: everything a solve reads, resolved |
| ``churn_baseline.py`` | the approved plan baseline and the pairing its reason requires |
| ``resolved_content.py`` | resolved content and immovable facts carried by ``SolveInputs`` |
| ``materialize.py`` | phase 1, what is placed unchecked, and the order candidates take |
| ``derivation.py`` | one block per determined placement, and one empty slot per Area slot |
| ``clauses.py`` | the ``bound`` clause a derived block carries, and the labels it renders |
| ``constraints.py`` | the hard-constraint vocabulary, the table, and the checker |
| ``state.py`` | a candidate placement, and the state of the week every rule judges it against |
| ``ordering.py`` | one key per collection the state holds, and the property every key holds |
| ``rules.py`` | each rule name paired with its check, and the thirteen in the table's order |
| ``occupancy.py`` | the five rules that ask whether a span is already spent |
| ``shape.py`` | the three rules about what length a block may take and where its bounds fall |
| ``allocation.py`` | the two rules about what an Area's own budget allows |
| ``immovability.py`` | the three rules about what may not move and what may not be intruded on |
| ``weights.py`` | the seven term weights and the four fitted parameters the objective applies |
| ``objective.py`` | ``evaluate``, the breakdown it returns, and how a raw term becomes a cost |
| ``terms.py`` | the seven raw measurements, each a fraction of something the week holds |
| ``preferred.py`` | whose preference applies to a block, and the four components of the misfit |
| ``reading.py`` | one reading of a plan the seven terms share, so no two of them derive it twice |
| ``figures.py`` | the minute figures a document carries, over the inputs and the blocks |
| ``candidates.py`` | the two kinds of content that bind late, and the demand each carries |
| ``tiebreak.py`` | the total order candidates are offered in, ending in an identity |
| ``attempt.py`` | what one solve has placed, left unfilled, and refused, and the log's bound |
| ``chunking.py`` | how a divided task's pieces are numbered, and when each half is decided |
| ``inheritance.py`` | the placements a solve inherits: derived, begun, and pinned |
| ``elastic.py`` | how long an elastic occurrence is placed for, and what bounds the choice |
| ``offering.py`` | one candidate plus one window into a checked, scored placement |
| ``binding.py`` | phase 2: content into the slots whose time the template already fixed |
| ``filling.py`` | phase 3: the cadence items and the remaining task work into the gaps |
| ``moves.py`` | the four move kinds, each as a candidate plan the objective judges |
| ``search.py`` | phase 4: bounded descent, accepting only a strict improvement |
| ``verdicts.py`` | phase 5: the probe's shortfalls plus the packing failures the attempt found |
| ``reasons.py`` | the record every block carries, projected from what the solve already decided |
| ``budget.py`` | how much work one solve may do, and where a caller may stop it |
| ``solve.py`` | the second entry point, its result, and the five phases in order |
| ``metrics.py`` | the families this package publishes, on the shared registry |
| ``errors.py`` | what a malformed resolved input is refused with |

The zero-ML rule is the load-bearing one: no language model sits in the placement loop and no ML
library is a dependency, which is what keeps the api image free of scipy, the solver testable
against literals, and ``syncr-learning`` replaceable without touching the request path.
"""

from syncr_solver.materialize import materialize
from syncr_solver.metrics import MaterializeCause, SolveOutcome
from syncr_solver.solve import SolveResult, solve

__all__ = ["MaterializeCause", "SolveOutcome", "SolveResult", "materialize", "solve"]
