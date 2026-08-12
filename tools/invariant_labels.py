"""The invariant-label census, and the check that the lookup resolves every label the tree cites.

An invariant label is a short identifier, an ``H`` number or a ``VE`` number, that a comment uses to
name one requirement the product's design places on the code. ``docs/invariants.md`` is the only
place in the repository that says what each one requires. Without it a label in a comment is a
pointer to nothing, so this check exists to keep that file total: every label a comment cites has a
row.

KEEP EXAMPLE LABELS OUT OF THE PROSE IN THIS DIRECTORY. These files are read by the census they
publish, so a label written out here becomes a citation this repository has to resolve and inflates
the figure the census reports for the trees a reader is asking about.

Run it to see what the tree cites:

    python3 tools/invariant_labels.py

Run the gate, which is what ``just lint`` runs:

    python3 tools/invariant_labels.py --check

GIT ANSWERS WHAT THE FILES ARE, through ``git ls-files --cached``, rather than a walk with a list
of directories to skip. The index is what is about to become the repository: it covers a file staged
but not yet committed, it cannot see a scratch file or a generated tree, and it grows a new package
without anyone remembering to add it here. Which of those files are read is a declared partition,
in :mod:`comments`.

THE CHECK IS ONE-DIRECTIONAL, and deliberately: a label with no row fails, a row nothing cites does
not. Comments that name a label are being replaced by comments that state what it requires, so the
citations trend to none while the rows stay: the file is what a reader consults, and its rows
outlive the last comment that pointed at them. A row nothing cites is printed, never failed.

THE SECOND DIRECTION IS WHAT KEEPS A SWEPT TREE SWEPT. Once a tree's comments state their
requirements, a label reappearing in one of them is a regression nothing above can see, because
every label resolves and so that check stays green. :func:`bare` fails on a citation anywhere
outside a tree :data:`PENDING` names, so the two cover one set between them and nothing falls
between: every path the reading reads is in exactly one of the two states, and the exempt state is
enumerated.

AN EXEMPTION CANNOT OUTLIVE THE SWEEP IT WAITS FOR. A named tree that cites no label fails, so the
entry goes with the change that empties it rather than staying behind to permit a relapse.

FOR THE SAME REASON THE CONTROL ON THIS GATE KEYS ON THE READING RATHER THAN ON WHAT IT FOUND. A
repository whose comments all state their requirement cites no label at all, and that is the state
this one is meant to reach, so a control keyed on citations would fail on success. Zero files read,
or no prose in the files read, is a broken reading and does fail.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import comments

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
LOOKUP: Final = Path("docs/invariants.md")

# The alphabet the reading matches, spelled out because it is the vocabulary rather than a claim
# about one. A token this pattern cannot match is a label nothing can find, which is the one hole in
# the reading: the pattern knows the families that exist, and it is crossed against the lookup in
# both directions, so a family in one and not the other fails rather than passing silently.
#
# Order does not matter, because the trailing digits and the boundary make the alternation
# backtrack: `V` before `VE` still reads a VE label as VE.
#
# The vocabulary is NOT derived from the lookup, which would be circular: deleting every row of a
# family would then delete the family from the pattern, and every citation of it would become
# invisible rather than unresolved.
FAMILIES: Final = ("VE", "OP", "PN", "PP", "H", "O", "R", "V")
LABEL: Final = re.compile(rf"\b(?:{'|'.join(FAMILIES)})\d{{1,2}}\b")

# A label-shaped token that is not a citation. ``H99`` is a fabricated rule name a solver test
# passes to the reason reader to prove the reading rejects a clause the solve never made, so it
# names no invariant and can have no row.
NOT_A_LABEL: Final[Mapping[str, str]] = {
    "H99": "a fabricated rule name a solver test uses as a negative control",
}

# The trees whose comments still name labels instead of stating what they require, each with the
# reason that is still true. A citation inside one is reported; a citation anywhere else fails.
#
# THIS IS THE WHOLE OF THE EXEMPTION, so the set the gate covers is every path the reading reads
# less these prefixes. An entry is deleted by the change that leaves its tree citing nothing, and
# the gate fails while an entry sits in front of a tree that cites none, so an exemption that has
# stopped being true cannot go on permitting a label.
PENDING: Final[Mapping[str, str]] = {
    "packages/syncr-solver": "its comments still name the labels rather than stating them",
}

_ROW: Final = re.compile(r"^\|\s*`(?P<label>[A-Za-z]+\d{1,2})`\s*\|\s*(?P<states>[^|]+?)\s*\|$")
_SEPARATOR: Final = re.compile(r"^\|[\s:-]+\|[\s:-]+\|$")
_HEADER: Final = "| Label | What it requires |"


@dataclass(frozen=True, slots=True)
class Citation:
    """One label, in one piece of prose, at one place."""

    label: str
    path: str
    line: int

    def __str__(self) -> str:
        return f"{self.path}:{self.line}"


@dataclass(frozen=True, slots=True)
class Lookup:
    """The lookup as read: the rows it carries, and everything wrong with the ones it does not."""

    rows: Mapping[str, str]
    problems: tuple[str, ...]

    @property
    def families(self) -> set[str]:
        return {label.rstrip("0123456789") for label in self.rows}


@dataclass(frozen=True, slots=True)
class Census:
    """One reading of the index: what it read, how much prose it saw, and what that prose cites."""

    paths: tuple[Path, ...]
    read: tuple[Path, ...]
    prose: int
    found: tuple[Citation, ...]


def tracked(root: Path) -> list[Path]:
    """Every path in the index, which is the repository as it is about to be committed."""
    listed = subprocess.run(
        # `git` from the PATH the developer and CI both have.
        ["git", "ls-files", "--cached", "-z"],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    paths = [root / name for name in listed.stdout.split("\0") if name]
    if not paths:
        raise RuntimeError(f"git listed no files under {root}, so this reading reads nothing")
    return paths


def census(paths: Iterable[Path], *, root: Path) -> Census:
    """One reading of those paths: the ones whose kind is read, their prose, and what it cites.

    Every read file is parsed, with no cheap pre-test for a label-shaped token in the text. Such
    a test cut the reading's cost by two thirds and made both of the control's figures a function
    of the citations: the files it skips are the files with nothing to find, so a repository that
    cites nothing reads almost none of itself, and the control cannot then tell a swept tree from a
    broken parser. The suite holds the read set to every tracked path of a read kind, so the
    pre-test cannot come back quietly.
    """
    every = tuple(sorted(paths))
    read: list[Path] = []
    pieces = 0
    found: list[Citation] = []
    for path in every:
        if comments.kind(path) not in comments.READ:
            continue
        read.append(path)
        relative = path.relative_to(root).as_posix()
        for line, piece in comments.prose(path, comments.text_of(path)):
            pieces += 1
            found.extend(
                Citation(label, relative, line)
                for label in LABEL.findall(piece)
                if label not in NOT_A_LABEL
            )
    return Census(paths=every, read=tuple(read), prose=pieces, found=tuple(found))


def lookup_of(root: Path) -> Lookup:
    """The lookup this repository ships, or one problem naming it when the file is not there."""
    path = root / LOOKUP
    if not path.is_file():
        return Lookup(rows={}, problems=(f"{LOOKUP} does not exist, so no label resolves at all",))
    return read_lookup(path.read_text(encoding="utf-8"))


def read_lookup(text: str) -> Lookup:
    """The lookup's rows, and a problem for every line that looks like a row and is not one."""
    rows: dict[str, str] = {}
    problems: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.startswith("|") or line == _HEADER or _SEPARATOR.match(line):
            continue
        row = _ROW.match(line)
        if row is None:
            problems.append(f"line {number} is a table row this reading cannot parse: {line!r}")
            continue
        label, states = row.group("label"), row.group("states")
        if label in rows:
            problems.append(f"line {number} is a second row for {label}")
        if LABEL.fullmatch(label) is None:
            problems.append(f"line {number} declares {label}, which no citation could match")
        if not states.endswith(".") or ". " in states:
            problems.append(f"line {number} states more or less than one sentence for {label}")
        rows[label] = states
    if not rows:
        problems.append("the lookup carries no rows at all, so it resolves nothing")
    return Lookup(rows=rows, problems=tuple(problems))


def unresolved(found: Iterable[Citation], lookup: Lookup) -> list[Citation]:
    """Every citation of a label the lookup does not resolve."""
    return [citation for citation in found if citation.label not in lookup.rows]


def uncited(found: Iterable[Citation], lookup: Lookup) -> list[str]:
    """Every label the lookup resolves that no comment cites."""
    cited = {citation.label for citation in found}
    return sorted(lookup.rows.keys() - cited, key=_in_family_order)


def _is_pending(path: str, pending: Iterable[str]) -> bool:
    return any(path == tree or path.startswith(f"{tree}/") for tree in pending)


def bare(taken: Census, *, root: Path, pending: Mapping[str, str] = PENDING) -> list[str]:
    """Every label a comment names outside a pending tree, and every exemption that is spent.

    The other direction of the gate. The check above asks whether a citation resolves, which stays
    green once every label has a row, so on its own it cannot see a label coming back into a comment
    that had been rewritten to state its requirement. This asks whether a comment names a label at
    all, everywhere except the trees named as not yet swept.

    A spent exemption fails: a named tree the reading has paths for and finds no citation in is a
    sweep that has landed, and its entry has to go with it. Scoped to trees the reading has paths
    for, so this holds over any repository rather than over this one's directory layout.
    """
    complaints = [
        f"{citation} names {citation.label} rather than stating what it requires: replace the "
        f"label with the sentence {LOOKUP} gives for it"
        for citation in taken.found
        if not _is_pending(citation.path, pending)
    ]
    cited = {citation.path for citation in taken.found}
    read = {path.relative_to(root).as_posix() for path in taken.read}
    return complaints + [
        f"{tree} is named as not yet swept and cites no label, so that sweep has landed: delete "
        f"its entry from PENDING in tools/invariant_labels.py"
        for tree in sorted(pending)
        if any(_is_pending(path, (tree,)) for path in read)
        and not any(_is_pending(path, (tree,)) for path in cited)
    ]


def _in_family_order(label: str) -> tuple[str, int]:
    return (label.rstrip("0123456789"), int(label.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")))


def _tree_of(relative: str) -> str:
    """The two outermost directories a citation sits in, or ``.`` for a file at the root."""
    return "/".join(Path(relative).parts[:-1][:2]) or "."


def _report(taken: Census, lookup: Lookup) -> None:
    labels = sorted({citation.label for citation in taken.found}, key=_in_family_order)
    per_label: dict[str, int] = {}
    per_tree: dict[str, int] = {}
    for citation in taken.found:
        per_label[citation.label] = per_label.get(citation.label, 0) + 1
        tree = _tree_of(citation.path)
        per_tree[tree] = per_tree.get(tree, 0) + 1

    if labels:
        print(f"{len(labels)} distinct invariant labels, cited {len(taken.found)} times")
        print("  " + " ".join(f"{label}({per_label[label]})" for label in labels))
        print("\nby tree")
        for tree, count in sorted(per_tree.items(), key=lambda pair: (-pair[1], pair[0])):
            print(f"  {tree:40} {count}")
    else:
        print("no invariant label is cited anywhere the census reads")
    kinds = len(comments.READ) + len(comments.SKIPPED)
    print(
        f"\nread {len(taken.read)} of {len(taken.paths)} tracked files over {kinds} declared kinds "
        f"({len(comments.READ)} read, {len(comments.SKIPPED)} skipped), and {taken.prose} pieces "
        f"of prose in them"
    )
    print(f"not read: {', '.join(f'{k} ({v})' for k, v in sorted(comments.SKIPPED.items()))}")
    print(f"not a label, by name: {', '.join(sorted(NOT_A_LABEL))}")
    waiting = sorted(tree for tree in PENDING if tree in per_tree)
    if waiting:
        listed = ", ".join(waiting)
        print(f"not yet swept, so a citation there is reported and not failed: {listed}")
    resolved = len(lookup.rows)
    print(
        f"\n{LOOKUP} resolves {resolved} labels; "
        f"{len(uncited(taken.found, lookup))} of them uncited"
    )


def check(taken: Census, lookup: Lookup) -> list[str]:
    """Everything wrong: an unresolved citation, a malformed lookup, an undecided kind of file."""
    complaints = list(lookup.problems)
    # THE CONTROL, AND IT KEYS ON THE READING RATHER THAN ON WHAT THE READING FOUND. Zero citations
    # is a state this repository is meant to reach, because a comment is better off stating a
    # requirement than naming it, so a control keyed on citations would fail on success. Zero files
    # read, or no prose in the files read, is a reading that cannot have found anything.
    if not taken.read:
        complaints.append(
            f"nothing was read: no kind this census reads appears among the {len(taken.paths)} "
            f"paths in the index, so a green result would say nothing"
        )
    elif not taken.prose:
        complaints.append(
            f"no comment and no docstring in any of the {len(taken.read)} files read, so this is a "
            f"broken reading rather than a repository that cites nothing"
        )
    for citation in unresolved(taken.found, lookup):
        complaints.append(
            f"{citation} cites {citation.label} and {LOOKUP} has no row for it: add one stating "
            f"what it requires, or spell the token so it does not read as an invariant label"
        )
    complaints += [
        f"{undecided} is a kind of file neither read nor skipped, so nothing decided whether a "
        f"label in it counts: declare it in tools/comments.py"
        for undecided in comments.undeclared(taken.paths)
    ]
    return complaints


def main(argv: Sequence[str]) -> int:
    """Print the census, and gate on it when asked."""
    taken = census(tracked(REPO_ROOT), root=REPO_ROOT)
    lookup = lookup_of(REPO_ROOT)
    _report(taken, lookup)
    if "--check" not in argv:
        return 0
    complaints = check(taken, lookup) + bare(taken, root=REPO_ROOT)
    if complaints:
        print(f"\n{len(complaints)} problem(s):", file=sys.stderr)
        for complaint in complaints:
            print(f"  {complaint}", file=sys.stderr)
        return 1
    print(f"\nevery cited label resolves in {LOOKUP}, and no swept tree names one")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
