"""What a revision's columns claim, and the writers that decide whether the claim is true.

``weight_set_version`` is not nullable and every writer records the version active at the write, so
the column answers "what was in force" for every row. It cannot answer "what chose this
arrangement", because a materialization evaluates no objective and records the active version all
the same. The column comment used to say it did, which is the claim this file holds.

``objective_breakdown`` is what tells the two cases apart, and it does so only while two things
stay true: the writer that weighs nothing passes an empty mapping, and a writer that weighed
something passes a cost per term even when every cost is zero. Both are asserted, because either
one changing turns the comment into prose that reads right and answers wrongly.

The writer set is DERIVED rather than listed. A name search over the repository finds the calls that
mention the column; it cannot say which of them writes a revision, so the reading here is a walk
that keys on the shape of a revision append. What it cannot see is stated at the walk.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import syncr_api
from syncr_api.plans.models import PlanRevision
from syncr_api.plans.production import NO_OBJECTIVE
from syncr_solver.objective import ObjectiveBreakdown
from syncr_solver.weights import OBJECTIVE_TERMS

if TYPE_CHECKING:
    from collections.abc import Iterable

BREAKDOWN_KEYWORD = "objective_breakdown"
REASON_KEYWORD = "reason"
APPEND = "append"


def _api_source_root() -> Path:
    assert syncr_api.__file__ is not None
    return Path(syncr_api.__file__).parent


def _column_comment() -> str:
    """The column comment as the mapped class carries it, on one line.

    Collapsed, because the prose is wrapped at the line length and a clause that spans a wrap is
    still the clause: keying on the newlines would redden the guard on a reflow.
    """
    assert PlanRevision.__doc__ is not None
    return " ".join(PlanRevision.__doc__.split())


def _empty_mappings(tree: ast.Module) -> set[str]:
    """Every module-level name in ``tree`` bound to an empty dict literal."""
    found: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, ast.AnnAssign):
            targets: Iterable[ast.expr] = [statement.target]
        elif isinstance(statement, ast.Assign):
            targets = statement.targets
        else:
            continue
        if not isinstance(statement.value, ast.Dict) or statement.value.keys:
            continue
        found.update(one.id for one in targets if isinstance(one, ast.Name))
    return found


def _appends_a_revision(node: ast.AST) -> bool:
    """Whether ``node`` is a call that appends a plan revision.

    Keyed on the shape rather than on a module list: an append carrying both a breakdown and a
    reason is a revision write, and nothing else in this package carries that pair to an
    ``append``. ``PlanRepository.append`` takes both keyword-only, so no writer can pass either
    positionally and slip past this.
    """
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr != APPEND:
        return False
    passed = {one.arg for one in node.keywords}
    return BREAKDOWN_KEYWORD in passed and REASON_KEYWORD in passed


def revision_writers(source_root: Path) -> dict[str, str]:
    """Every module that appends a revision, and what it passes as the breakdown.

    The value is ``""`` for a writer passing an empty mapping, either as a literal or through a
    module-level name bound to one, and the expression's own text otherwise.

    WHAT THIS CANNOT SEE, because a walk that hides its edge is worse than none. A name bound to an
    empty mapping in ANOTHER module reads as non-empty here, since the binding is resolved per file.
    A call assembled through ``getattr`` or a keyword dictionary carries no keyword this walk can
    read. Both would understate the empty writers, and the module set below is asserted whole rather
    than as a floor, so either arriving alongside a fourth writer still reddens.
    """
    found: dict[str, str] = {}
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        empties = _empty_mappings(tree)
        for node in ast.walk(tree):
            if not _appends_a_revision(node):
                continue
            assert isinstance(node, ast.Call)
            (passed,) = [one for one in node.keywords if one.arg == BREAKDOWN_KEYWORD]
            text = ast.unparse(passed.value)
            empty = (isinstance(passed.value, ast.Dict) and not passed.value.keys) or (
                text in empties
            )
            found[str(path.relative_to(source_root))] = "" if empty else text
    return found


# ---------------------------------------------------------------------------
# What the comment says
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "clause",
    [
        pytest.param("the set in force when the row was written", id="the-reading-it-has"),
        pytest.param(
            "rather than a statement about what chose the arrangement",
            id="the-reading-it-does-not-have",
        ),
        pytest.param(
            "A write that evaluated no objective records the active version too",
            id="why-the-two-readings-differ",
        ),
        pytest.param("``objective_breakdown`` is what tells those apart", id="the-tell-is-named"),
        pytest.param(
            "empty exactly when the write evaluated no objective", id="what-the-tell-reads"
        ),
        pytest.param(
            "otherwise carries a cost for every objective term", id="the-other-side-of-the-tell"
        ),
    ],
)
def test_the_column_comment_states_the_reading_the_column_has(clause: str) -> None:
    assert clause in _column_comment()


@pytest.mark.parametrize(
    ("pattern", "shape"),
    [
        pytest.param(r"weights? produced (?:it|this)", "weights produced it", id="the-false-claim"),
        pytest.param(
            r"which weights (?:it was |were )?(?:produced|used)",
            "which weights were used",
            id="the-false-claim-reworded",
        ),
    ],
)
def test_the_comment_no_longer_claims_the_column_names_what_produced_the_document(
    pattern: str, shape: str
) -> None:
    # `shape` is the control: a pattern matching nothing anywhere would pass the comment assertion
    # while looking like a guard, so each one is shown to match its own shape first.
    assert re.search(pattern, shape, re.IGNORECASE) is not None
    assert re.search(pattern, _column_comment(), re.IGNORECASE) is None


# ---------------------------------------------------------------------------
# Whether the tell the comment names actually tells
# ---------------------------------------------------------------------------


def test_the_writer_that_weighs_nothing_passes_an_empty_breakdown() -> None:
    assert NO_OBJECTIVE == {}


def test_a_solve_states_a_cost_per_term_even_when_every_cost_is_zero() -> None:
    # The other half of the tell, and the half that can break quietly. A breakdown that omitted its
    # zero costs would let a solve whose plan cost nothing write the same empty mapping a
    # materialization writes, and the two cases would stop being distinguishable at all.
    costless = ObjectiveBreakdown(
        deadline_risk=0.0,
        budget_deviation=0.0,
        time_of_day_misfit=0.0,
        fragmentation=0.0,
        churn=0.0,
        context_switch=0.0,
        staleness=0.0,
    )

    assert tuple(costless.costs()) == OBJECTIVE_TERMS
    assert costless.costs() != {}


def test_exactly_one_writer_appends_a_revision_that_weighed_nothing() -> None:
    """The population, read off the package rather than listed here.

    Asserted whole rather than as a floor: a fourth writer, or a third writer passing an empty
    mapping, reddens this deliberately. Either one is a change to what the column comment may
    claim, and the comment is what this file exists to keep true.
    """
    writers = revision_writers(_api_source_root())

    assert set(writers) == {
        "approvals/service.py",
        "plans/adoption.py",
        "plans/production.py",
    }
    assert [module for module, passed in writers.items() if passed == ""] == ["plans/production.py"]


def test_the_walk_reports_a_second_writer_that_weighed_nothing(tmp_path: Path) -> None:
    # The control, and it runs the WALK rather than the pattern: a reading whose subject set
    # resolved to no files would pass forever. Two invented writers, one passing a literal and one
    # passing a name bound to an empty mapping, because the classification has two branches.
    (tmp_path / "literal.py").write_text(
        "await self._revisions.append(objective_breakdown={}, reason='materialized')\n",
        encoding="utf-8",
    )
    (tmp_path / "named.py").write_text(
        "NOTHING: dict[str, object] = {}\n"
        "await self._revisions.append(objective_breakdown=NOTHING, reason='materialized')\n",
        encoding="utf-8",
    )
    (tmp_path / "weighed.py").write_text(
        "await self._revisions.append(objective_breakdown=solved.costs(),"
        " reason='user_approved')\n",
        encoding="utf-8",
    )

    found = revision_writers(tmp_path)

    assert found == {"literal.py": "", "named.py": "", "weighed.py": "solved.costs()"}


def test_the_walk_reads_an_append_rather_than_any_call_carrying_a_breakdown(tmp_path: Path) -> None:
    # The other control. The package hands a breakdown to a proposal slot, an edit context and a
    # candidate as well, and a walk that counted those would report writers of the plan of record
    # that write nothing of the kind.
    (tmp_path / "elsewhere.py").write_text(
        "self._pending.replace(objective_breakdown={}, reason='auto_applied_fill')\n"
        "Candidate(objective_breakdown={}, reason='auto_applied_fill')\n"
        "EditContext(objective_breakdown={})\n",
        encoding="utf-8",
    )

    assert revision_writers(tmp_path) == {}
