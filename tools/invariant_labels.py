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

# The families, longest prefix first so a ``VE`` label reads as VE rather than as V. A token this
# pattern cannot match is a label nothing can find, which is the one hole in the reading: the
# pattern knows the families that exist, and a row is checked against it so a family added to the
# lookup without being added here fails rather than passing silently.
LABEL: Final = re.compile(r"\b(?:VE|OP|PN|PP|H|O|R|V)\d{1,2}\b")

# A label-shaped token that is not a citation. ``H99`` is a fabricated rule name a solver test
# passes to the reason reader to prove the reading rejects a clause the solve never made, so it
# names no invariant and can have no row.
NOT_A_LABEL: Final[Mapping[str, str]] = {
    "H99": "a fabricated rule name a solver test uses as a negative control",
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


def citations(paths: Iterable[Path], *, root: Path) -> list[Citation]:
    """Every invariant label cited in the prose of every path whose kind is read."""
    found: list[Citation] = []
    for path in sorted(paths):
        if comments.kind(path) not in comments.READ:
            continue
        text = path.read_text(encoding="utf-8")
        # Nothing label-shaped anywhere in the file, so nothing in its prose either. The reading
        # parses over a thousand Python files and this keeps a gate a developer runs under a second
        # per hundred of them; it can only skip a file no citation could have been found in.
        if LABEL.search(text) is None:
            continue
        relative = path.relative_to(root).as_posix()
        for line, piece in comments.prose(path, text):
            found.extend(
                Citation(label, relative, line)
                for label in LABEL.findall(piece)
                if label not in NOT_A_LABEL
            )
    return found


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


def _in_family_order(label: str) -> tuple[str, int]:
    return (label.rstrip("0123456789"), int(label.lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ")))


def _tree_of(relative: str) -> str:
    return "/".join(Path(relative).parts[:2])


def _report(found: Sequence[Citation], lookup: Lookup, paths: Sequence[Path]) -> None:
    labels = sorted({citation.label for citation in found}, key=_in_family_order)
    per_label: dict[str, int] = {}
    per_tree: dict[str, int] = {}
    for citation in found:
        per_label[citation.label] = per_label.get(citation.label, 0) + 1
        tree = _tree_of(citation.path)
        per_tree[tree] = per_tree.get(tree, 0) + 1

    print(f"{len(labels)} distinct invariant labels, cited {len(found)} times")
    print("  " + " ".join(f"{label}({per_label[label]})" for label in labels))
    print("\nby tree")
    for tree, count in sorted(per_tree.items(), key=lambda pair: (-pair[1], pair[0])):
        print(f"  {tree:40} {count}")
    read = [path for path in paths if comments.kind(path) in comments.READ]
    print(f"\nread {len(read)} of {len(paths)} tracked files, by comment spelling")
    print(f"not read: {', '.join(f'{k} ({v})' for k, v in sorted(comments.SKIPPED.items()))}")
    print(f"not a label, by name: {', '.join(sorted(NOT_A_LABEL))}")
    resolved = len(lookup.rows)
    print(f"\n{LOOKUP} resolves {resolved} labels; {len(uncited(found, lookup))} of them uncited")


def check(found: Sequence[Citation], lookup: Lookup, paths: Sequence[Path]) -> list[str]:
    """Everything wrong: an unresolved citation, a malformed lookup, an undecided kind of file."""
    complaints = list(lookup.problems)
    if not found:
        complaints.append(
            f"nothing to check: the reading found no citation at all in {len(paths)} tracked files"
        )
    for citation in unresolved(found, lookup):
        complaints.append(
            f"{citation} cites {citation.label} and {LOOKUP} has no row for it: add one stating "
            f"what it requires, or spell the token so it does not read as an invariant label"
        )
    complaints += [
        f"{undecided} is a kind of file neither read nor skipped, so nothing decided whether a "
        f"label in it counts: declare it in tools/comments.py"
        for undecided in comments.undeclared(paths)
    ]
    return complaints


def main(argv: Sequence[str]) -> int:
    """Print the census, and gate on it when asked."""
    paths = tracked(REPO_ROOT)
    found = citations(paths, root=REPO_ROOT)
    lookup = read_lookup((REPO_ROOT / LOOKUP).read_text(encoding="utf-8"))
    _report(found, lookup, paths)
    if "--check" not in argv:
        return 0
    complaints = check(found, lookup, paths)
    if complaints:
        print(f"\n{len(complaints)} problem(s):", file=sys.stderr)
        for complaint in complaints:
            print(f"  {complaint}", file=sys.stderr)
        return 1
    print(f"\nevery cited label resolves in {LOOKUP}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
