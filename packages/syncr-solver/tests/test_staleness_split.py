"""What ``StalenessSplit`` answers, and what the solver says about where that answer reaches.

Two questions, and they fail in different ways.

**What the split answers** is a comparison over two inputs, so the table below drives each input
alone, the comparison in both directions, the tie, and the week with nothing falling behind. A case
per input is not enough: a reading keyed to one of them passes every case that names the other.

**What the solver SAYS about the split** is prose, and prose has no test unless something reads it.
The reading here is an equality over each corrected unit rather than a substring of it, because a
substring is blind to a sentence added BESIDE the one it holds: a paragraph that takes the answer
back leaves every substring intact. Equality reddens on an addition, an edit and a removal alike,
and the cost is real -- an edit to a paragraph this file pins for a different reason reddens too.

A ban runs beside the equalities, over every prose unit of every solver module, because the claim
being corrected was stated in four places and a correction to one is what this epic keeps rejecting.
The ban is what notices a fifth. Its width is a case rather than a claim: eighteen plausible
restatements are driven through it, and what it still cannot see is stated at it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

import syncr_solver
from syncr_solver import objective
from syncr_solver.objective import _require_a_split_for_a_charged_staleness
from syncr_solver.terms import StalenessInput, StalenessSplit

if TYPE_CHECKING:
    from collections.abc import Iterator


# ---------------------------------------------------------------------------
# What the split answers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cadence", "rotation", "expected"),
    [
        pytest.param(0, 0, None, id="nothing-falling-behind"),
        pytest.param(30, 0, StalenessInput.CADENCE, id="the-cadence-alone"),
        pytest.param(0, 30, StalenessInput.ROTATION, id="the-rotation-alone"),
        pytest.param(90, 30, StalenessInput.CADENCE, id="the-cadence-carries-more"),
        pytest.param(30, 90, StalenessInput.ROTATION, id="the-rotation-carries-more"),
        pytest.param(45, 45, StalenessInput.CADENCE, id="a-tie-goes-to-the-cadence"),
    ],
)
def test_which_input_the_split_reports_as_dominant(
    cadence: int, rotation: int, expected: StalenessInput | None
) -> None:
    """Both inputs, both directions of the comparison, the tie, and the empty week.

    The tie is the row nothing else in the suite holds, and it is a decision rather than an
    accident: the two are compared in the order they are declared in, so equal minutes report the
    cadence.
    """
    split = StalenessSplit(
        cadence_minutes=cadence, rotation_minutes=rotation, due_minutes=cadence + rotation
    )

    assert split.dominant() is expected


# ---------------------------------------------------------------------------
# The reading: a module's prose, by the unit a sentence can be added to
# ---------------------------------------------------------------------------


def paragraphs(text: str) -> tuple[str, ...]:
    """``text`` split on blank lines, each paragraph squeezed onto one line.

    Squeezed because the prose is wrapped at the line length and a clause that spans a wrap is still
    the clause: keying on the newlines would redden every one of these on a reflow.
    """
    return tuple(" ".join(block.split()) for block in text.split("\n\n") if block.strip())


def bullets(text: str) -> tuple[str, ...]:
    """Every ``-`` item of ``text``, squeezed onto one line, so one item is one unit.

    A bullet list is one paragraph, and pinning the paragraph would make a reader of one bullet the
    owner of its siblings' wording.
    """
    found: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- "):
            found.append([stripped[2:]])
        elif found and stripped:
            found[-1].append(stripped)
        elif not stripped:
            found.append([])
    return tuple(" ".join(" ".join(item).split()) for item in found if item)


def comment_blocks(source: str) -> tuple[str, ...]:
    """Every run of consecutive whole-line comments, squeezed, with the markers taken off.

    The BLOCK rather than the line, for the reason equality is used at all: a sentence appended to a
    comment leaves every line of it unchanged. A comment after code on the same line is not read,
    which is a limit rather than a decision about it.
    """
    found: list[list[str]] = [[]]
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            found[-1].append(stripped.lstrip("#").strip())
        elif found[-1]:
            found.append([])
    return tuple(" ".join(" ".join(block).split()) for block in found if block)


def prose_units(source: str) -> Iterator[str]:
    """Every unit of prose in a Python source: each docstring's paragraphs, and each comment block.

    A string standing alone as a statement counts, which is what a docstring is and what a block
    written where a comment would be is. A string passed as an argument or assigned to a name is a
    value rather than prose, so neither is read here.
    """
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            yield from paragraphs(node.value.value)
    yield from comment_blocks(source)


def solver_modules() -> tuple[Path, ...]:
    assert syncr_solver.__file__ is not None
    return tuple(sorted(Path(syncr_solver.__file__).parent.rglob("*.py")))


# ---------------------------------------------------------------------------
# What each corrected unit says, pinned by equality
# ---------------------------------------------------------------------------

THE_SPLITS_READING: Final = (
    "The two inputs of the staleness term, and which of them dominated.",
    "**One term with two inputs, not two terms.** An overdue cadence item and a rotation that has "
    "not advanced are the same complaint, that something is falling behind, and splitting them "
    "doubles a weight the learning layer must fit from sparse data.",
    "**Which input dominated is carried by the objective BREAKDOWN, and the reason record does not "
    "name it.** The ``dominant`` clause names the TERM, ``staleness``, and holds no field an input "
    "could go in, so a block's record says the week is falling behind and not which half of it is. "
    "The breakdown reaches a plan revision as its seven costs alone, so the split does not survive "
    "that row either: it is readable for as long as the solve that computed it and no longer.",
    "The two figures PARTITION the due occurrences rather than overlapping: an occurrence's "
    "content comes from a rotation cursor or it does not, so no occurrence is in both and the "
    "share below cannot count one twice.",
)

THE_VOCABULARYS_READING: Final = (
    "The two complaints the staleness term carries, named so the split can say which dominated.",
    'Two members and no third. A term with two inputs has two names; a member for "neither" would '
    "be a name for the absence of a cost, which the split reports as nothing instead.",
)

THE_DOMINANT_READING: Final = (
    "Which input carried more of the cost, or nothing because neither carried any.",
    "A tie goes to the cadence, which is the order the two are declared in. Nothing to report is "
    "reported as nothing rather than as a name at zero: a split naming a dominant input that cost "
    "nothing states something no arithmetic here computed.",
)

THE_GUARDS_READING: Final = (
    "Staleness above zero names which of its two inputs it came from.",
    "The same shape as the churn guard: the term is one number over two inputs, and the split is "
    "the only thing that says which of them the charge came from. A charge whose split is empty is "
    "a composition that read one and dropped the other.",
)

THE_FIELDS_READING: Final = (
    "Which of the staleness term's two inputs dominated, and both figures. Not a cost: the term "
    "above is the cost, and the `dominant` clause carries that term rather than either input."
)

THE_BULLETS_READING: Final = (
    "``staleness_split`` names which of the staleness term's two inputs dominated, which is the "
    "one place that reading exists: no clause of a reason record and no stored column carries it;"
)


def test_the_split_states_where_which_input_dominated_is_carried() -> None:
    assert StalenessSplit.__doc__ is not None
    assert paragraphs(StalenessSplit.__doc__) == THE_SPLITS_READING


def test_the_input_vocabulary_names_the_split_as_what_says_which_dominated() -> None:
    assert StalenessInput.__doc__ is not None
    assert paragraphs(StalenessInput.__doc__) == THE_VOCABULARYS_READING


def test_the_dominant_reading_states_what_a_split_at_zero_would_claim() -> None:
    assert StalenessSplit.dominant.__doc__ is not None
    assert paragraphs(StalenessSplit.dominant.__doc__) == THE_DOMINANT_READING


def test_the_split_guard_states_what_the_split_is_the_only_source_of() -> None:
    assert _require_a_split_for_a_charged_staleness.__doc__ is not None
    assert paragraphs(_require_a_split_for_a_charged_staleness.__doc__) == THE_GUARDS_READING


def test_the_breakdowns_field_comment_names_the_term_the_clause_carries() -> None:
    """Read as a comment BLOCK, so a sentence appended beside this one reddens rather than hides."""
    assert objective.__file__ is not None
    source = Path(objective.__file__).read_text(encoding="utf-8")

    assert THE_FIELDS_READING in comment_blocks(source)


def test_the_breakdown_states_that_the_split_reaches_nothing_further() -> None:
    assert objective.__doc__ is not None

    assert THE_BULLETS_READING in bullets(objective.__doc__)


# ---------------------------------------------------------------------------
# The ban: no module of the solver says a reader names which input dominated
# ---------------------------------------------------------------------------

# A reader as the SUBJECT of a positive naming verb, with an input as the object. The verb has to
# follow the reader through nothing but a modal or one comma-delimited aside, so a denial reads as a
# denial: "the reason record DOES NOT name it" puts `does` between the two and matches nothing here.
#
# Every vocabulary here was widened once, against the eighteen restatements in `RESTATEMENTS` below.
# The first version caught five, which is why that table is a case rather than a paragraph: a ban's
# width is a figure, and a figure nothing reads goes stale.
_READER: Final = r"(?:\brecords?\b|\bclauses?\b|\bpanels?\b|\bscreens?\b|the interface)"
# The same reader where the sentence names it as an object, so the article and up to two qualifying
# words in front of it are part of the shape: "by the reason record", "the week screen".
_A_READER: Final = rf"(?:the |a |its |this )?(?:\w+'?s? ){{0,2}}{_READER}"
_ASIDE: Final = r"(?:,[^.,]{0,40},)?"
_MODALS: Final = r"(?:(?:can|could|may|will|would|still|also|already|itself)\s+)*"
_NAMES: Final = (
    r"(?:nam(?:e|es|ing)|says?|states?|reports?|reads?|carr(?:y|ies|ying)|hold(?:s|ing)?"
    r"|surfac(?:e|es|ing)|expos(?:e|es|ing)|explain(?:s|ing)?|render(?:s|ing)?|show(?:s|ing)?)"
)
_PASSIVE: Final = (
    r"(?:named|said|stated|reported|read|carried|held|surfaced|exposed|explained|rendered|shown)"
)
_AN_INPUT: Final = (
    r"which (?:input|of them|of the two|dominated)"
    r"|(?:input|one|half)s? (?:that )?dominat"
    r"|dominant (?:staleness )?input"
)

# (id, pattern, a unit the pattern must match)
BANNED: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "a-reader-names-which-input",
        rf"{_READER}{_ASIDE}\s+{_MODALS}{_NAMES}\b[^.]{{0,60}}(?:{_AN_INPUT})",
        "Nothing is lost in explainability, because the reason record can still name which input "
        "dominated, and this is where it reads that from.",
    ),
    (
        "a-reader-is-what-names-it",
        rf"(?:this|that|it) is what {_A_READER}{_ASIDE}\s+{_MODALS}{_NAMES}\b",
        "Which of the staleness term's two inputs dominated, and both figures. Not a cost: the "
        "term above is the cost, and this is what the reason record names.",
    ),
    (
        "an-input-is-named-by-a-reader",
        rf"(?:{_AN_INPUT})[^.]{{0,30}}(?:is|are) {_PASSIVE} by {_A_READER}",
        "which input dominated is named by the reason record",
    ),
)

# The other edge. Each is the SHAPE of a denial rather than a whole sentence, because what the ban
# must admit is the shape: a reader named as what does NOT carry the input, and a clause named as
# carrying the term instead. Every one is a fragment this package now states, so a widening that
# swallowed a denial fails here rather than in review.
ADMITTED: Final[tuple[tuple[str, str], ...]] = (
    ("the-record-does-not-name-it", "and the reason record does not name it"),
    ("the-clause-names-the-term", "The ``dominant`` clause names the TERM, ``staleness``"),
    (
        "the-clause-carries-the-term",
        "the `dominant` clause carries that term rather than either input",
    ),
    ("the-split-names-it-instead", "named so the split can say which dominated"),
    ("the-breakdown-carries-it", "Which input dominated is carried by the objective BREAKDOWN"),
    ("no-clause-and-no-column", "no clause of a reason record and no stored column carries it"),
    (
        "the-record-says-what-it-does-say",
        "so a block's record says the week is falling behind and not which half of it is",
    ),
)

# Eighteen restatements of the claim, in the shapes a writer would plausibly reach for. The first
# version of the ban caught five: two verb vocabularies, an aside between a reader and its verb, a
# reader the list did not hold, and the passive all walked past it.
#
# `the-clauses-own-verb` is the one that mattered. `carries` is the verb the corrected field comment
# uses, so the register this package now writes in was the register the ban could not read, and a
# writer copying the corrected wording would have reached for exactly the word it was blind to.
RESTATEMENTS: Final[tuple[tuple[str, str], ...]] = (
    ("surfaces", "the reason record surfaces which input dominated"),
    ("exposes", "the reason record exposes which input dominated"),
    ("explains", "the reason record explains which input dominated"),
    ("the-clauses-own-verb", "the clause carries the dominant input"),
    ("holds", "the clause holds which of the two dominated"),
    ("renders", "the panel renders which input dominated"),
    ("shows", "the clause shows which input dominated"),
    ("an-aside", "the reason record, for every block, names which input dominated"),
    ("a-longer-aside", "the clause, on every block of the week, says which input dominated"),
    ("a-screen", "the week screen names which input dominated"),
    ("a-blocks-record", "the block's record names which input dominated"),
    ("a-bare-record", "a record carries the dominant input"),
    ("the-passive", "which input dominated is named by the reason record"),
    ("the-passive-carried", "which input dominated is carried by the clause"),
    ("the-passive-reported", "which of the two dominated is reported by the panel"),
    ("the-original", "the reason record can still name which input dominated"),
    ("the-deictic", "this is what the reason record names"),
    ("the-deictic-widened", "it is what the panel surfaces"),
)


@pytest.mark.parametrize(("name", "pattern", "shape"), BANNED, ids=[row[0] for row in BANNED])
def test_the_ban_matches_the_claim_where_it_was_written(
    name: str, pattern: str, shape: str
) -> None:
    # The control, and it is the whole reason the emptiness below means anything: a pattern that
    # matches nothing reads exactly like a tree that states the claim nowhere. Each shape is the
    # sentence this ticket corrected, verbatim from the blob it corrected.
    assert re.search(pattern, shape, re.IGNORECASE) is not None, name


@pytest.mark.parametrize(("name", "shape"), RESTATEMENTS, ids=[row[0] for row in RESTATEMENTS])
def test_the_ban_catches_a_plausible_restatement_of_the_claim(name: str, shape: str) -> None:
    # The width, as a figure. Each of these says the thing the correction denies, in a register the
    # first version of the ban could not read, and this is what stops the vocabularies from being an
    # opinion about what a writer will reach for.
    caught = [row[0] for row in BANNED if re.search(row[1], shape, re.IGNORECASE)]

    assert caught, name


@pytest.mark.parametrize(("name", "shape"), ADMITTED, ids=[row[0] for row in ADMITTED])
def test_the_ban_admits_a_sentence_that_denies_the_claim(name: str, shape: str) -> None:
    # The other edge. A ban wide enough to catch the assertion and its denial would force the
    # correction to say nothing at all, so the denial's own shape is shown to pass.
    for _, pattern, _ in BANNED:
        assert re.search(pattern, shape, re.IGNORECASE) is None, name


def test_no_module_of_the_solver_says_a_reader_names_which_input_dominated() -> None:
    """The population, read off the package rather than listed.

    WHAT THIS CANNOT SEE, in the shapes measured rather than the one first declared. A reader this
    vocabulary does not hold, since the list is closed and "the week grid" is as plausible as "the
    week screen". A naming verb outside the twelve, and the verb set is the vocabulary that let five
    restatements past the first version. An aside between a reader and its verb that is not
    comma-delimited: "the reason record for every block names it" passes. A claim whose input object
    sits BEFORE the reader's verb outside the two forms the second and third patterns spell; the one
    unit of that shape in this package is the field comment, pinned by equality above. A claim in a
    string passed as a value rather than standing alone, which is not prose. A comment after code on
    the same line, which ``comment_blocks`` does not read.
    """
    found: list[str] = []
    for path in solver_modules():
        for unit in prose_units(path.read_text(encoding="utf-8")):
            for name, pattern, _ in BANNED:
                if re.search(pattern, unit, re.IGNORECASE):
                    found.append(f"{path.name} {name}: {unit[:110]}")

    assert found == []


def test_the_reading_finds_the_claim_when_a_module_states_it(tmp_path: Path) -> None:
    # The control for the WALK rather than for the patterns: a unit reader that resolved nothing
    # would report an empty tree forever. One module per unit kind, because the two are read by
    # different halves of `prose_units`.
    (tmp_path / "in_a_docstring.py").write_text(
        '"""A term.\n\nThe reason record can still name which input dominated.\n"""\n',
        encoding="utf-8",
    )
    (tmp_path / "in_a_comment.py").write_text(
        "# Which of the two inputs dominated.\n"
        "# Not a cost: this is what the reason record names.\n",
        encoding="utf-8",
    )
    (tmp_path / "in_a_value.py").write_text(
        'MESSAGE = "the reason record can still name which input dominated"\n',
        encoding="utf-8",
    )

    found = {
        path.name: [
            name
            for unit in prose_units(path.read_text(encoding="utf-8"))
            for name, pattern, _ in BANNED
            if re.search(pattern, unit, re.IGNORECASE)
        ]
        for path in sorted(tmp_path.glob("*.py"))
    }

    assert found == {
        "in_a_comment.py": ["a-reader-is-what-names-it"],
        "in_a_docstring.py": ["a-reader-names-which-input"],
        "in_a_value.py": [],
    }
