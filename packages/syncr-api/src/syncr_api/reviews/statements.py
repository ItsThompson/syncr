"""What the review says in words, in one table rather than a formatting decision per row.

A statement is non-null exactly when it says something the figures beside it do not, which is the
convention ``off_plan_statement`` already follows. A period with a
denominator, confirmed days and a proposal carries none of these: its figures speak for themselves,
and a sentence restating them would be noise on every read.

The basis sentences are a total function over ``ProposalBasis``, so a member added to that
vocabulary fails to render rather than rendering nothing.
"""

from __future__ import annotations

from typing import Final

from syncr_domain.budget_review import ProposalBasis

NO_PLAN_OF_RECORD: Final = (
    "This week holds no plan, so it has no discretionary time to divide and no Area has a target "
    "in it. Build a day shape and a week pattern, and the figures appear when the week is planned."
)

NO_CONFIRMED_DAY: Final = (
    "No day of this week has been answered for, so nothing here is measured behaviour. Confirm a "
    "day on Today and this week's composition appears."
)

NO_CONFIRMED_DAY_IN_THE_QUARTER: Final = (
    "No day of the last quarter has been answered for, so there is no trend and nothing to "
    "propose. Confirming a day is what turns a plan into a record."
)

NOTHING_IS_APPLIED_WITHOUT_ACCEPTANCE: Final = (
    "syncr noticed these patterns and has changed nothing. A promotion edits your template only "
    "when you accept it, and declining one does not raise it again for a while."
)

_BASIS_STATEMENTS: Final[dict[ProposalBasis, str]] = {
    ProposalBasis.FLOOR_HOLDS_IT: (
        "Unchanged: this Area declares a floor, and the floor is what holds its time rather than "
        "the share."
    ),
    ProposalBasis.NEVER_MET: "The target was not met in any of the confirmed weeks.",
    ProposalBasis.SUSTAINED_UNDER: "Sustained under target across the confirmed weeks.",
    ProposalBasis.SUSTAINED_OVER: "Sustained over target across the confirmed weeks.",
    ProposalBasis.ALREADY_THERE: (
        "Unchanged: the observed share is close enough to the target that half the gap is nothing."
    ),
}


def basis_statement(basis: ProposalBasis) -> str:
    """The sentence for one proposal's reason."""
    return _BASIS_STATEMENTS[basis]


def confirmed_day_statement(confirmed_days: int) -> str | None:
    """Why this week's charts hold nothing, or ``None`` when they hold something."""
    return None if confirmed_days > 0 else NO_CONFIRMED_DAY


def quarter_statement(confirmed_days: int) -> str | None:
    """Why the trend holds nothing, or ``None`` when it holds something."""
    return None if confirmed_days > 0 else NO_CONFIRMED_DAY_IN_THE_QUARTER


def denominator_statement(discretionary_minutes: int | None) -> str | None:
    """Why every figure of this week is absent, or ``None`` when the week was planned."""
    return None if discretionary_minutes is not None else NO_PLAN_OF_RECORD


def period_statement(*, confirmed: int, unconfirmed: int, off_plan: int) -> str:
    """How much of the reviewed period the retrospective rests on. Always a sentence.

    ``US-REV-04``: every review states the number of confirmed and unconfirmed days in its period,
    and reports off-plan days SEPARATELY from unconfirmed ones. Always present, because "most of
    this week was answered for" and "almost none of it was" are two readings the figures beside them
    do not distinguish, and a caller that had to infer which it was reading would be inferring it.

    A period with no confirmed day says so rather than leaving a chart to render nothing, which is
    the third clause of the same story.
    """
    off_plan_clause = f", and {off_plan} declared off-plan" if off_plan else ""
    if confirmed == 0:
        return (
            f"No day of this period was answered for: {unconfirmed} hold blocks nobody has "
            f"confirmed{off_plan_clause}. Nothing below is measured behaviour, so there is nothing "
            "to chart until a day is confirmed on Today."
        )
    return (
        f"{confirmed} confirmed {_days(confirmed)} and {unconfirmed} unconfirmed"
        f"{off_plan_clause}. Only the confirmed days contribute to the figures below."
    )


def _days(count: int) -> str:
    return "day" if count == 1 else "days"


def proposal_statement(*, confirmed_weeks: int, required_weeks: int) -> str:
    """What the proposal half of the review rests on, or why there is not one yet.

    Always a sentence, because both readings are a statement the reader needs: one says how much
    evidence the proposal has and the other says how much is missing. It is the one place the
    product's own rule is spoken, that syncr never re-cuts the budget on its own.
    """
    if confirmed_weeks < required_weeks:
        return (
            f"A proposal needs {required_weeks} fully confirmed weeks and {confirmed_weeks} "
            f"{'exists' if confirmed_weeks == 1 else 'exist'}, so this review shows the gap "
            "between actual and target only. A budget cut from a few weeks would fit a quarter to "
            "one unusual month."
        )
    return (
        f"Derived from {confirmed_weeks} fully confirmed weeks, moving each target half the way to "
        "what actually happened. syncr never re-cuts the budget on its own: nothing here is "
        "applied until you approve it, and you may adjust any figure first."
    )
