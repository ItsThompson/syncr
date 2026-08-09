"""The census, the lookup, and the gate that crosses one against the other.

The two mutations the gate exists to survive are asserted here rather than described: a row removed
from the lookup leaves the citations it resolved unresolved, and a label planted in a comment with
no row is reported with its file, its line and the remedy.

KEEP EXAMPLE LABELS OUT OF THE PROSE IN THIS FILE. A docstring here is read by the census this file
tests, so a label written into one becomes a citation the repository has to resolve. The planted
labels below are string values, which the reading does not count.
"""

from __future__ import annotations

import subprocess
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from invariant_labels import (
    LOOKUP,
    NOT_A_LABEL,
    REPO_ROOT,
    Citation,
    Lookup,
    check,
    citations,
    main,
    read_lookup,
    tracked,
    uncited,
    unresolved,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class AtHead:
    """One reading of the repository, shared by every test that asks about it."""

    paths: list[Path]
    found: list[Citation]
    lookup: Lookup


@pytest.fixture(scope="module")
def head() -> AtHead:
    paths = tracked(REPO_ROOT)
    return AtHead(
        paths=paths,
        found=citations(paths, root=REPO_ROOT),
        lookup=read_lookup((REPO_ROOT / LOOKUP).read_text(encoding="utf-8")),
    )


def a_row_of(head: AtHead) -> str:
    """The label the repository cites most, so a test that drops one drops a cited one."""
    return Counter(citation.label for citation in head.found).most_common(1)[0][0]


class TestTheLookupResolvesEveryLabelTheTreeCites:
    def test_every_label_a_comment_cites_has_a_row(self, head: AtHead) -> None:
        assert unresolved(head.found, head.lookup) == []

    def test_the_reading_found_citations_to_check(self, head: AtHead) -> None:
        """The control. The assertion above passes over an empty reading too."""
        assert head.found
        assert len({citation.label for citation in head.found}) > 1

    def test_the_gate_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The command `just lint` runs, in this process."""
        assert main(["--check"]) == 0
        assert "every cited label resolves" in capsys.readouterr().out

    def test_the_lookup_the_repository_ships_is_well_formed(self, head: AtHead) -> None:
        assert head.lookup.problems == ()


class TestALabelWithNoRow:
    def test_a_label_planted_in_a_comment_is_unresolved(self, head: AtHead, tmp_path: Path) -> None:
        """One half of the mutation: a comment gains a label the lookup never resolved."""
        planted = tmp_path / "planted.py"
        planted.write_text("# H42 is what this one has to do\n", encoding="utf-8")

        found = citations([planted], root=tmp_path)

        assert unresolved(found, head.lookup) == [Citation("H42", "planted.py", 1)]

    def test_the_complaint_names_the_place_the_lookup_and_the_remedy(
        self, head: AtHead, tmp_path: Path
    ) -> None:
        planted = tmp_path / "planted.py"
        planted.write_text("value = 1  # H42 applies here\n", encoding="utf-8")

        complaints = check(citations([planted], root=tmp_path), head.lookup, [planted])

        assert len(complaints) == 1
        assert "planted.py:1" in complaints[0]
        assert "H42" in complaints[0]
        assert str(LOOKUP) in complaints[0]

    def test_dropping_a_row_leaves_the_citations_it_resolved_unresolved(self, head: AtHead) -> None:
        """The other half of the mutation: the lookup loses a row the tree still cites."""
        dropped = a_row_of(head)
        without = Lookup(
            rows={label: states for label, states in head.lookup.rows.items() if label != dropped},
            problems=(),
        )

        gone = unresolved(head.found, without)

        assert gone
        assert {citation.label for citation in gone} == {dropped}


class TestTheLookupsShape:
    def test_a_row_the_reading_cannot_parse_is_a_problem(self) -> None:
        lookup = read_lookup(
            _a_lookup_of("| `H1` | what it requires. |", "| H2 | no label markers around it. |")
        )

        assert lookup.problems == (
            "line 4 is a table row this reading cannot parse: "
            "'| H2 | no label markers around it. |'",
        )

    def test_a_second_row_for_one_label_is_a_problem(self) -> None:
        lookup = read_lookup(
            _a_lookup_of("| `H1` | what it requires. |", "| `H1` | something else. |")
        )

        assert lookup.problems == ("line 4 is a second row for H1",)

    def test_more_than_one_sentence_is_a_problem(self) -> None:
        """A row is one sentence, because a paragraph is what a comment cannot carry."""
        lookup = read_lookup(_a_lookup_of("| `H1` | one thing. And another. |"))

        assert lookup.problems == ("line 3 states more or less than one sentence for H1",)

    def test_a_row_no_citation_could_match_is_a_problem(self) -> None:
        """A family in the lookup and not in the pattern is a row nothing can ever reach."""
        lookup = read_lookup(_a_lookup_of("| `ZZ4` | what it requires. |"))

        assert lookup.problems == ("line 3 declares ZZ4, which no citation could match",)

    def test_a_lookup_with_no_rows_at_all_is_a_problem(self) -> None:
        lookup = read_lookup("# The invariant labels\n\nNothing here.\n")

        assert lookup.rows == {}
        assert lookup.problems == ("the lookup carries no rows at all, so it resolves nothing",)

    def test_the_header_and_the_separator_are_not_rows(self) -> None:
        lookup = read_lookup(_a_lookup_of("| `H1` | what it requires. |"))

        assert lookup.rows == {"H1": "what it requires."}


class TestWhatIsNotACitation:
    def test_the_fabricated_rule_name_is_not_a_citation(self, tmp_path: Path) -> None:
        """It names no invariant, so it can have no row, so counting it would be unpassable."""
        planted = tmp_path / "planted.py"
        planted.write_text("# H99 is fabricated, and H9 is not\n", encoding="utf-8")

        found = citations([planted], root=tmp_path)

        assert [citation.label for citation in found] == ["H9"]

    def test_it_is_excluded_by_name_with_a_reason(self) -> None:
        assert NOT_A_LABEL["H99"]

    def test_the_repository_cites_it_nowhere(self, head: AtHead) -> None:
        """Its occurrences are values a test passes, which the reading does not count anyway."""
        assert [citation for citation in head.found if citation.label == "H99"] == []


class TestTheReading:
    def test_an_index_with_no_files_refuses_rather_than_reporting_clean(
        self, tmp_path: Path
    ) -> None:
        subprocess.run(  # noqa: S603 - a fixed argv, and no shell
            ["git", "init", "--quiet", str(tmp_path)],  # noqa: S607
            check=True,
        )

        with pytest.raises(RuntimeError, match="listed no files"):
            tracked(tmp_path)

    def test_a_resolved_label_nothing_cites_is_reported_rather_than_failed(self) -> None:
        """The rows outlive the comments that pointed at them, so an uncited row is not a fault."""
        lookup = read_lookup(_a_lookup_of("| `H1` | what it requires. |"))

        assert uncited([], lookup) == ["H1"]
        assert check([Citation("H1", "x.py", 1)], lookup, [_ANY_PATH]) == []


def _a_lookup_of(*rows: str) -> str:
    return "\n".join(("| Label | What it requires |", "|---|---|", *rows)) + "\n"


_ANY_PATH = REPO_ROOT / "justfile"
