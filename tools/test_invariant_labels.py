"""The census, the lookup, and the gate that crosses one against the other.

The two mutations the gate exists to survive are asserted here rather than described: a row removed
from the lookup leaves the citations it resolved unresolved, and a label planted in a comment with
no row is reported with its file, its line and the remedy.

KEEP EXAMPLE LABELS OUT OF THE PROSE IN THIS FILE. A docstring here is read by the census this file
tests, so a label written into one becomes a citation the repository has to resolve. The planted
labels below are string values, which the reading does not count.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

import comments
import invariant_labels
from invariant_labels import (
    FAMILIES,
    LOOKUP,
    NOT_A_LABEL,
    REPO_ROOT,
    Census,
    Citation,
    Lookup,
    census,
    check,
    lookup_of,
    main,
    read_lookup,
    tracked,
    uncited,
    unresolved,
)


@dataclass(frozen=True, slots=True)
class AtHead:
    """One reading of the repository, shared by every test that asks about it."""

    taken: Census
    lookup: Lookup

    @property
    def found(self) -> tuple[Citation, ...]:
        return self.taken.found


@pytest.fixture(scope="module")
def head() -> AtHead:
    return AtHead(
        taken=census(tracked(REPO_ROOT), root=REPO_ROOT),
        lookup=lookup_of(REPO_ROOT),
    )


class TestTheLookupResolvesEveryLabelTheTreeCites:
    def test_every_label_a_comment_cites_has_a_row(self, head: AtHead) -> None:
        assert unresolved(head.found, head.lookup) == []

    def test_the_reading_read_the_kinds_it_declares(self, head: AtHead) -> None:
        """The control, and it asks about the reading rather than about what the reading found.

        Non-emptiness is not the property: a reading that covered three files of nineteen hundred
        would satisfy it, and that is exactly what a pre-test on the label pattern produced. The
        expected set is computed here from the reading's own paths and the declared partition, so
        there is no figure to maintain, and any file of a read kind that goes unread reddens this.

        It survives the state the sweeps are meant to reach, where every comment states its
        requirement and no comment cites a label.
        """
        declared = [path for path in head.taken.paths if comments.kind(path) in comments.READ]

        assert list(head.taken.read) == declared
        assert head.taken.prose > len(head.taken.read)

    def test_the_gate_passes(self, capsys: pytest.CaptureFixture[str]) -> None:
        """The command `just lint` runs, in this process."""
        assert main(["--check"]) == 0
        assert "every cited label resolves" in capsys.readouterr().out

    def test_the_lookup_the_repository_ships_is_well_formed(self, head: AtHead) -> None:
        assert head.lookup.problems == ()

    def test_the_pattern_and_the_lookup_declare_the_same_families(self, head: AtHead) -> None:
        """A family in one and not the other is a row nothing reaches or a token nothing finds."""
        assert set(FAMILIES) == head.lookup.families


class TestALabelWithNoRow:
    def test_a_label_planted_in_a_comment_is_unresolved(self, head: AtHead, tmp_path: Path) -> None:
        """One half of the mutation: a comment gains a label the lookup never resolved."""
        planted = tmp_path / "planted.py"
        planted.write_text("# H42 is what this one has to do\n", encoding="utf-8")

        found = census([planted], root=tmp_path).found

        assert unresolved(found, head.lookup) == [Citation("H42", "planted.py", 1)]

    def test_the_complaint_names_the_place_the_lookup_and_the_remedy(
        self, head: AtHead, tmp_path: Path
    ) -> None:
        planted = tmp_path / "planted.py"
        planted.write_text("value = 1  # H42 applies here\n", encoding="utf-8")

        complaints = check(census([planted], root=tmp_path), head.lookup)

        assert len(complaints) == 1
        assert "planted.py:1" in complaints[0]
        assert "H42" in complaints[0]
        assert str(LOOKUP) in complaints[0]
        assert "add one stating what it requires" in complaints[0]

    def test_dropping_a_row_leaves_the_citations_it_resolved_unresolved(self, head: AtHead) -> None:
        """The other half of the mutation, over the lookup this repository ships.

        Stated against a planted citation rather than the live tree's, so it keeps biting once the
        sweeps have left the tree citing nothing.
        """
        dropped = next(iter(head.lookup.rows))
        without = Lookup(
            rows={label: states for label, states in head.lookup.rows.items() if label != dropped},
            problems=(),
        )

        gone = unresolved([Citation(dropped, "x.py", 12)], without)

        assert [citation.label for citation in gone] == [dropped]

    def test_a_malformed_lookup_fails_the_gate(self) -> None:
        """The wire between a shape problem and the exit code, which the shape tests never cross."""
        lookup = read_lookup(_a_lookup_of("| `H1` | one thing. And another. |"))

        complaints = check(_a_census(), lookup)

        assert complaints == ["line 3 states more or less than one sentence for H1"]

    def test_a_lookup_that_is_not_there_is_a_complaint_rather_than_a_traceback(
        self, tmp_path: Path
    ) -> None:
        lookup = lookup_of(tmp_path)

        assert lookup.rows == {}
        assert lookup.problems == (f"{LOOKUP} does not exist, so no label resolves at all",)


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

    def test_a_row_that_does_not_end_its_sentence_is_a_problem(self) -> None:
        """The other half of the same check: less than one sentence is not one sentence either."""
        lookup = read_lookup(_a_lookup_of("| `H1` | what it requires |"))

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

        found = census([planted], root=tmp_path).found

        assert [citation.label for citation in found] == ["H9"]

    def test_it_is_excluded_by_name_with_a_reason(self) -> None:
        assert NOT_A_LABEL["H99"]

    def test_the_fixture_that_carries_it_carries_it_as_a_value(self) -> None:
        """The claim the exclusion rests on, read without the exclusion applied.

        Asserting that the census reports no such citation would pass whatever the file said,
        because the name is filtered before a citation exists. This reads the file's own prose
        instead, so it bites the moment someone writes the token into a comment there.
        """
        path = REPO_ROOT / "packages/syncr-solver/tests/test_reasons.py"
        text = comments.text_of(path)

        assert "H99" in text
        assert all("H99" not in piece for _, piece in comments.prose(path, text))


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

    def test_a_reading_that_read_nothing_is_a_complaint(self) -> None:
        """The control on the gate itself: it must not pass by having read nothing."""
        lookup = read_lookup(_a_lookup_of("| `H1` | what it requires. |"))

        complaints = check(Census(paths=(Path("a.png"),), read=(), prose=0, found=()), lookup)

        assert complaints == [
            "nothing was read: no kind this census reads appears among the 1 paths in the index, "
            "so a green result would say nothing"
        ]

    def test_a_reading_that_found_no_prose_at_all_is_a_complaint(self) -> None:
        """A collapsed classifier reads the files and returns nothing, which is not a clean tree."""
        lookup = read_lookup(_a_lookup_of("| `H1` | what it requires. |"))

        complaints = check(Census(paths=(_ANY_PATH,), read=(_ANY_PATH,), prose=0, found=()), lookup)

        assert complaints == [
            "no comment and no docstring in any of the 1 files read, so this is a broken reading "
            "rather than a repository that cites nothing"
        ]

    def test_a_repository_that_cites_nothing_passes(self) -> None:
        """The state the sweeps are specified to reach: prose everywhere, no label anywhere.

        A control keyed on citations found rather than on the reading fails here, which would turn
        this gate red on the day the last citation is restated and leave no one able to fix it.
        """
        lookup = read_lookup(_a_lookup_of("| `H1` | what it requires. |"))

        swept = Census(paths=(_ANY_PATH,), read=(_ANY_PATH,), prose=40, found=())

        assert check(swept, lookup) == []
        assert uncited(swept.found, lookup) == ["H1"]

    def test_an_undeclared_kind_is_a_complaint(self) -> None:
        """The clause the gate reports it through, which the tree test cannot defend on its own."""
        lookup = read_lookup(_a_lookup_of("| `H1` | what it requires. |"))
        undecided = Path("a/b.rs")

        complaints = check(
            Census(paths=(_ANY_PATH, undecided), read=(_ANY_PATH,), prose=1, found=()), lookup
        )

        assert len(complaints) == 1
        assert ".rs" in complaints[0]
        assert "tools/comments.py" in complaints[0]

    def test_a_resolved_label_nothing_cites_is_reported_rather_than_failed(self) -> None:
        """The rows outlive the comments that pointed at them, so an uncited row is not a fault."""
        lookup = read_lookup(_a_lookup_of("| `H1` | what it requires. |"))

        assert uncited([], lookup) == ["H1"]
        assert check(_a_census(), lookup) == []


class TestTheCommandItself:
    """The two exits, driven over a repository built for the purpose.

    The gate's failing exit is the branch that makes the whole check decoration if it is wrong, and
    nothing in this repository can drive it while this repository passes.
    """

    def test_the_gate_fails_and_names_the_label(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(invariant_labels, "REPO_ROOT", _a_repository(tmp_path))

        assert main(["--check"]) == 1
        assert "H42" in capsys.readouterr().err

    def test_the_plain_invocation_reports_without_gating(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Asking what the tree cites is not asking whether it passes."""
        monkeypatch.setattr(invariant_labels, "REPO_ROOT", _a_repository(tmp_path))

        assert main([]) == 0
        printed = capsys.readouterr()
        assert "distinct invariant labels" in printed.out
        assert "every cited label resolves" not in printed.out
        assert printed.err == ""

    def test_the_report_names_the_root_rather_than_the_file_for_a_citation_at_the_top(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The by-tree column groups citations, so a file at the root belongs to the root."""
        monkeypatch.setattr(invariant_labels, "REPO_ROOT", _a_repository(tmp_path))

        main([])

        printed = capsys.readouterr().out
        assert re.search(r"^  \.\s+1$", printed, re.MULTILINE)
        assert "cited.py " not in printed


def _a_repository(root: Path) -> Path:
    """A repository of two files: a lookup of one row, and a comment citing a label it lacks."""
    (root / "docs").mkdir(parents=True)
    (root / "docs/invariants.md").write_text(
        _a_lookup_of("| `H1` | what it requires. |"), encoding="utf-8"
    )
    (root / "cited.py").write_text("# H42 is what this one has to do\n", encoding="utf-8")
    subprocess.run(  # noqa: S603 - a fixed argv, and no shell
        ["git", "init", "--quiet", str(root)],  # noqa: S607
        check=True,
    )
    subprocess.run(  # noqa: S603 - a fixed argv, and no shell
        ["git", "-C", str(root), "add", "docs/invariants.md", "cited.py"],  # noqa: S607
        check=True,
    )
    return root


def _a_lookup_of(*rows: str) -> str:
    return "\n".join(("| Label | What it requires |", "|---|---|", *rows)) + "\n"


def _a_census() -> Census:
    """A reading that worked, so a test about the lookup is not also a test about the reading."""
    return Census(
        paths=(_ANY_PATH,), read=(_ANY_PATH,), prose=12, found=(Citation("H1", "x.py", 1),)
    )


_ANY_PATH = REPO_ROOT / "justfile"
