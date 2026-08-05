"""Print what the reference week's reason records hold, by kind and by block.

``python -m tests.measure_reasons`` from the member's directory. A read of the shipped modules,
outside pytest, so the figures a changeset quotes are the ones the code produces.
"""

from __future__ import annotations

from collections import Counter

from syncr_domain.reasons import CLAUSE_BUDGET, MAX_CLAUSES
from syncr_solver import solve
from tests.objective_weeks import hand_tuned_weights
from tests.reference_week import reference_week


def main() -> None:
    result = solve(reference_week(), hand_tuned_weights())
    blocks = result.document.blocks
    counted: Counter[str] = Counter()
    for block in blocks:
        counted.update(type(clause).__name__ for clause in block.reason.clauses)
    print(f"blocks {len(blocks)}  log rows {len(result.blocked_log)}")
    print(f"clauses {sum(counted.values())}  budget ceiling {MAX_CLAUSES} per block")
    for kind, allowed in CLAUSE_BUDGET.items():
        print(f"  {kind.__name__:12} {counted[kind.__name__]:4}   at most {allowed} per block")
    widest = max(blocks, key=lambda block: len(block.reason.clauses))
    print(f"most clauses on one block: {len(widest.reason.clauses)}  {widest.title}")
    for block in blocks:
        if len(block.reason.clauses) > 1:
            kinds = ", ".join(type(clause).__name__ for clause in block.reason.clauses)
            print(f"  {block.origin.value:15} {block.title:34} {kinds}")


if __name__ == "__main__":
    main()
