"""What ``candidates.py`` says about a queue habit's draw, held against being reopened.

The rule is prose, and prose has no test unless something reads it. Two readings, because they fail
differently.

**The paragraph is pinned by equality**, so an edit to the statement reddens instead of being
absorbed the way a substring reading absorbs one.

**A ban runs beside it**, over the module's own text, refusing the four shapes a deferral takes: a
rule owed, a rule nobody states, a ticket that carries the question, and a question called open. The
equality cannot see any of them, because a paragraph that takes the answer back is added BESIDE the
paragraph that gives it and leaves it untouched.

The ban reads the module's whole source rather than its prose alone: a deferral is a deferral
wherever it sits, and the stricter reading needs no walker of its own. What neither reading can see
is a deferral worded in terms none of the four shapes spell, and a deferral in a module other than
this one: the draw is stated here and nowhere else, so this is where the reading is.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

from syncr_solver import candidates

# The rule, as the module states it. Pinned whole: the reason a discharge is not the solver's is
# half the statement, and a paragraph holding only the answer could lose it silently.
THE_RULES_READING: Final = (
    "**A queue habit's session is its own demand, and drawing a task does not net that task's "
    'minutes.** The habit says "an hour of this Area, three times a week" and the task says how '
    "much work it needs, and a user who declared both declared both, so a week holds the cadence "
    "AND the task's own remaining work. Discharging the work instead is not this package's to do, "
    "for two reasons. The figure such a discharge would reduce, "
    "``EligibleTask.remaining_minutes``, arrives already netted, so reducing it here is the "
    "re-netting ``inputs.py`` is shaped to prevent. And the assembler that nets it cannot know "
    "WHICH task the draw will pick, so it would have to reserve the habit's minutes against a task "
    "chosen by a rule of its own, which makes the choice the producer's rather than the solver's. "
    "What the overlap costs is read by ``budget_deviation``, which compares the minutes an Area "
    "receives against what it was budgeted and so charges them as far as they take that Area past "
    "its target."
)

# The sentence the rule replaced, as a value rather than as prose, so the shapes below are held
# against the words that were actually there rather than against a paraphrase of them.
THE_DEFERRAL_THAT_WAS_THERE: Final = (
    "Whether a session should discharge the work it is named after needs a rule nothing in this "
    "spec states, and ticket 1372 carries it."
)

# A question called open, appended beside an answer rather than replacing it. The shape that gets
# past a reading of the answer's own paragraph.
A_REOPENING_BESIDE_THE_ANSWER: Final = (
    "Whether a session should discharge the work it draws is still open, and the paragraph above "
    "stands in for an answer nobody has given yet."
)

# (id, pattern, a text the pattern must match)
BANNED: Final[tuple[tuple[str, str, str], ...]] = (
    ("a-rule-is-owed", r"needs? an? (?:rule|decision|policy|answer)", THE_DEFERRAL_THAT_WAS_THERE),
    (
        "nobody-states-it",
        r"nothing (?:in this spec |anywhere |here )?states",
        THE_DEFERRAL_THAT_WAS_THERE,
    ),
    ("a-ticket-carries-it", r"ticket \d+ carries", THE_DEFERRAL_THAT_WAS_THERE),
    (
        "the-question-is-open",
        r"(?:whether|question)[^.]{0,90}(?:is|remains) (?:still )?open",
        A_REOPENING_BESIDE_THE_ANSWER,
    ),
)

# The other edge. A ban wide enough to catch the answer, or a sentence that names the question in
# order to answer it, would force the statement to say nothing at all.
ADMITTED: Final[tuple[tuple[str, str], ...]] = (
    ("the-rule-itself", THE_RULES_READING),
    (
        "the-question-named-in-order-to-answer-it",
        "Whether a session discharges the work it draws is answered here rather than left open.",
    ),
)


def paragraphs(text: str) -> tuple[str, ...]:
    """``text`` split on blank lines, each paragraph squeezed onto one line.

    Squeezed because the prose is hand-wrapped and a clause spanning a wrap is still the clause:
    keying on the newlines would redden this on a reflow that changed no word.
    """
    return tuple(" ".join(block.split()) for block in text.split("\n\n") if block.strip())


def deferrals_in(text: str) -> list[str]:
    """Every banned shape this text states, by name."""
    return [
        name for name, pattern, _ in BANNED if re.search(pattern, text, re.IGNORECASE) is not None
    ]


def the_modules_source() -> str:
    assert candidates.__file__ is not None
    return Path(candidates.__file__).read_text(encoding="utf-8")


def test_the_module_states_that_a_queue_session_is_its_own_demand() -> None:
    """The rule and its reason, pinned as one paragraph of the module's own docstring."""
    assert candidates.__doc__ is not None

    assert THE_RULES_READING in paragraphs(candidates.__doc__)


def test_nothing_in_the_module_leaves_the_rule_owed_to_somebody_else() -> None:
    """The census, and its first arm is what makes the second one an answer.

    A read that reached the wrong file, or an empty one, states no deferral either. So the same text
    the ban is run over is the text the pinned paragraph is parsed out of.
    """
    source = the_modules_source()
    stated = ast.get_docstring(ast.parse(source))

    assert stated is not None
    assert THE_RULES_READING in paragraphs(stated)
    assert deferrals_in(source) == []


@pytest.mark.parametrize(("name", "pattern", "shape"), BANNED, ids=[row[0] for row in BANNED])
def test_each_banned_shape_matches_the_words_it_is_keyed_to(
    name: str, pattern: str, shape: str
) -> None:
    # The control on the ban's own edge: a pattern that matched nothing would read exactly like a
    # module that defers nothing. Three of the four are held against the sentence this rule
    # replaced, verbatim; the fourth against a reopening, the shape the equality cannot see.
    assert re.search(pattern, shape, re.IGNORECASE) is not None, name


@pytest.mark.parametrize(("name", "shape"), ADMITTED, ids=[row[0] for row in ADMITTED])
def test_the_ban_admits_the_answer_and_a_sentence_that_names_the_question(
    name: str, shape: str
) -> None:
    assert deferrals_in(shape) == [], name


def test_the_reading_finds_a_deferral_in_a_module_that_states_one(tmp_path: Path) -> None:
    # The control keyed to what the census covers -- a module's text -- rather than to the patterns
    # above: a reading that resolved nothing would report a clean module forever.
    stated = tmp_path / "defers.py"
    stated.write_text(f'"""A draw.\n\n{THE_DEFERRAL_THAT_WAS_THERE}\n"""\n', encoding="utf-8")

    assert deferrals_in(stated.read_text(encoding="utf-8")) == [
        "a-rule-is-owed",
        "nobody-states-it",
        "a-ticket-carries-it",
    ]
