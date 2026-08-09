"""Where a file's prose is: its comments, and the strings it uses as prose.

A citation only rots when it sits in prose. A string a fixture passes as a VALUE is not prose: the
solver's constraint-rule vocabulary is spelled exactly the way an invariant label is, so a rule name
passed as an argument must not read as a citation. So the reading has to separate a comment from a
value, and cannot do it by matching a line.

Two mechanisms, one per language family, because the exact answer is cheap in Python and needs a
scanner everywhere else:

Python is read with :mod:`tokenize` and :mod:`ast`. Every ``COMMENT`` token counts, so a comment
after code on the same line counts, and every string that stands alone as a statement counts, which
covers a docstring and a triple-quoted block written where a comment would be. A string passed as an
argument or assigned to a name is neither.

Everything else is read with a scanner that walks characters and holds one state, because a comment
marker inside a quoted value is not a comment: ``"https://example.test"`` opens no comment, and
``key: "a # b"`` opens none either. A quoted value ends at a newline unless it opened with a
backtick, so an apostrophe in ordinary prose cannot swallow the rest of the file.

WHAT IS READ AND WHAT IS NOT is a declared partition over every kind of file the repository holds,
keyed on the suffix or, where there is none, the filename. A kind is read when its comments have a
spelling this module knows. Documentation is not read: it explains labels rather than citing them,
and ``docs/invariants.md`` names every one of them. The partition is exhaustive on purpose: a kind
in neither table is a file type nobody decided about, which is how a whole tree comes to be
unscanned while a scan over it reports clean.
"""

from __future__ import annotations

import ast
import io
import tokenize
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping
    from pathlib import Path

    Prose = Callable[[str], Iterator[tuple[int, str]]]


class Unreadable(RuntimeError):
    """A file whose language this module claims to know and could not read after all."""


def python_prose(text: str) -> Iterator[tuple[int, str]]:
    """Every comment and every stand-alone string in a Python source text, with its line."""
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            yield token.start[0], token.string
    for node in ast.walk(ast.parse(text)):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            yield node.lineno, node.value.value


def comment_reader(*, line: str, block: tuple[str, str] | None, quotes: str) -> Prose:
    """A reader for a language whose comments open with ``line`` or with ``block``."""

    def read(text: str) -> Iterator[tuple[int, str]]:
        index = 0
        number = 1
        length = len(text)
        while index < length:
            character = text[index]
            if character == "\n":
                number += 1
                index += 1
            elif text.startswith(line, index):
                end = text.find("\n", index)
                end = length if end == -1 else end
                yield number, text[index:end]
                index = end
            elif block is not None and text.startswith(block[0], index):
                end = text.find(block[1], index + len(block[0]))
                end = length if end == -1 else end + len(block[1])
                yield number, text[index:end]
                number += text.count("\n", index, end)
                index = end
            elif character in quotes:
                index, number = _past_the_value(text, index, number, character)
            else:
                index += 1

    return read


def _past_the_value(text: str, index: int, number: int, quote: str) -> tuple[int, int]:
    """The position just after a quoted value, and the line it ends on.

    A value that opened with a backtick may hold newlines. Any other closes at the end of its line
    whether or not its quote was ever closed, so one apostrophe cannot make the rest of the file
    invisible to the reading.
    """
    index += 1
    while index < len(text):
        character = text[index]
        if character == "\\":
            index += 2
            continue
        if character == quote:
            return index + 1, number
        if character == "\n":
            number += 1
            if quote != "`":
                return index + 1, number
        index += 1
    return index, number


_HASH: Final = comment_reader(line="#", block=None, quotes="'\"")
_SLASH: Final = comment_reader(line="//", block=("/*", "*/"), quotes="'\"`")
_DASH: Final = comment_reader(line="--", block=("/*", "*/"), quotes="'\"")

READ: Final[Mapping[str, Prose]] = {
    ".py": python_prose,
    ".ts": _SLASH,
    ".tsx": _SLASH,
    ".mjs": _SLASH,
    ".css": _SLASH,
    ".sql": _DASH,
    ".yml": _HASH,
    ".toml": _HASH,
    ".lock": _HASH,
    ".ini": _HASH,
    ".sh": _HASH,
    ".mako": _HASH,
    ".service": _HASH,
    ".timer": _HASH,
    ".example": _HASH,
    ".gitignore": _HASH,
    ".prettierignore": _HASH,
    ".dockerignore": _HASH,
    "justfile": _HASH,
    "Dockerfile": _HASH,
    "Caddyfile": _HASH,
}

SKIPPED: Final[Mapping[str, str]] = {
    ".md": "documentation, which resolves labels rather than citing them",
    ".html": "documentation, and its rendered scripts carry no citation",
    ".json": "no comment syntax, and a lockfile's integrity digests hold label-shaped substrings",
    ".baseline": "the secret-scan baseline, which is generated JSON",
    ".ics": "calendar fixtures, which are a wire format with no comment syntax",
    ".txt": "a golden fixture compared byte for byte",
    ".typed": "an empty marker file",
    ".python-version": "one version string",
    ".png": "binary",
}


def kind(path: Path) -> str:
    """What this path's comment spelling is keyed on: its suffix, or its name when it has none."""
    return path.suffix or path.name


def prose(path: Path, text: str) -> Iterator[tuple[int, str]]:
    """Every piece of prose in ``text``, read the way this path's language spells a comment.

    A file this module cannot read after all is raised rather than skipped, and the message names
    it: a skip would report a clean file for a file nobody read, and a parser error names no path.
    """
    try:
        yield from READ[kind(path)](text)
    except (SyntaxError, tokenize.TokenError) as broken:
        raise Unreadable(f"{path} does not read as {kind(path)}: {broken}") from broken


def undeclared(paths: Iterable[Path]) -> list[str]:
    """The kinds of file that are in neither table, so nobody has decided how to read them."""
    return sorted({kind(path) for path in paths} - set(READ) - set(SKIPPED))
