"""The iCalendar lexer: unfolding, content lines, escapes, and component grouping.

Every hostile property of the wire format is absorbed here, so nothing above this module
sees a fold, a CRLF, or a backslash escape.

**Unfolding.** RFC 5545 section 3.1 lets a publisher break a long line by inserting CRLF
followed by one space or tab; the continuation belongs to the previous line with the
whitespace removed. Publishers fold at 75 octets, mid-word, so a title arrives split.

**Line numbers survive unfolding.** A rejected component names the line it began on in the
feed AS DELIVERED, because that is the line a publisher can look at. So each content line
records where its first physical line was, and the folded remainder is counted but not
renumbered.

**CRLF variance.** The standard says CRLF; real feeds emit LF, and a few emit lone CR.
All three are line breaks here.

**Escapes.** ``\\n`` is a newline, ``\\N`` is the same, and ``\\\\``, ``\\;``, ``\\,`` are
the literal characters. A trailing lone backslash is kept as itself rather than raising:
the value is content, and refusing an event because its title ends in a backslash would
lose occupancy over a typo.

**Parameters are a multimap on the line, not a dict.** ``TZID`` appears once in practice,
but ``VALUE=DATE`` and a ``TZID`` can appear together and a quoted parameter value can
carry a colon or a semicolon, so the split is done character by character rather than by
``str.split``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from syncr_api.calendars.ics_errors import MalformedValue

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

# How deep a feed may nest components. A real one nests three (``VCALENDAR`` holding a ``VEVENT``
# holding a ``VALARM``), so this is enormous headroom and anything past it is a broken export or a
# hostile body rather than a calendar.
MAX_COMPONENT_DEPTH: Final = 100

# Any of the three line breaks a real feed uses, in order of preference so a CRLF is one
# break rather than two.
_LINE_BREAK: Final = re.compile(r"\r\n|\n|\r")

# What RFC 5545 permits at the start of a folded continuation.
_FOLD_PREFIX: Final = (" ", "\t")

_BEGIN: Final = "BEGIN"
_END: Final = "END"
VEVENT: Final = "VEVENT"

# The escape sequences a TEXT value may carry, and what each one means. `\N` is `\n`'s
# upper-case form and means the same thing.
_ESCAPES: Final = {"n": "\n", "N": "\n", "\\": "\\", ";": ";", ",": ",", ":": ":", '"': '"'}


@dataclass(frozen=True, slots=True)
class ContentLine:
    """One unfolded content line: ``NAME;PARAM=VALUE:the value``.

    ``line`` is the physical line the content line STARTED on, so a folded property
    reports where a publisher would find it.
    """

    name: str
    params: tuple[tuple[str, str], ...]
    value: str
    line: int

    def param(self, key: str) -> str | None:
        """The first value of parameter ``key``, case-insensitively, or ``None``."""
        wanted = key.upper()
        return next((value for name, value in self.params if name == wanted), None)


def unfold(text: str) -> Iterator[tuple[int, str]]:
    """The feed's content lines, each with the physical line number it began on.

    A continuation line contributes its content and no line number of its own. A blank
    line is dropped: publishers leave them between components and they carry nothing.
    """
    pending: list[str] = []
    started_at = 0
    for number, physical in enumerate(_LINE_BREAK.split(text), start=1):
        if physical[:1] in _FOLD_PREFIX and pending:
            pending.append(physical[1:])
            continue
        if pending:
            yield started_at, "".join(pending)
            pending = []
        if not physical.strip():
            continue
        started_at = number
        pending = [physical]
    if pending:
        yield started_at, "".join(pending)


def parse_content_line(raw: str, line: int) -> ContentLine | None:
    """One unfolded line as a content line, or ``None`` when it has no name and value.

    A line with no colon is not a content line. Feeds do emit them (a stray byte-order
    mark, a truncated final line), and skipping one is right: it names no property, so
    there is nothing for a caller to reject an event over.
    """
    head, separator, value = _split_on_unquoted_colon(raw)
    if not separator:
        return None
    name, params = _split_parameters(head)
    if not name:
        return None
    return ContentLine(name=name.upper(), params=params, value=value, line=line)


def unescape(value: str) -> str:
    """A TEXT value with its escapes resolved.

    A backslash before an unlisted character keeps both, because that is not an escape
    the standard defines and guessing at it would silently change a title.
    """
    if "\\" not in value:
        return value
    out: list[str] = []
    characters = iter(value)
    for character in characters:
        if character != "\\":
            out.append(character)
            continue
        following = next(characters, "")
        if following == "":
            out.append("\\")
        else:
            out.append(_ESCAPES.get(following, f"\\{following}"))
    return "".join(out)


@dataclass(frozen=True, slots=True)
class Component:
    """One ``BEGIN``/``END`` block, its content lines, and where it began.

    Nested components are kept as children rather than flattened, because a ``VEVENT``'s
    ``VALARM`` carries a ``DTSTART`` of its own and folding the two together would let an
    alarm's trigger be read as the event's start.
    """

    name: str
    lines: tuple[ContentLine, ...]
    children: tuple[Component, ...]
    line: int

    def all_values(self, name: str) -> tuple[ContentLine, ...]:
        """Every content line of this component named ``name``."""
        wanted = name.upper()
        return tuple(line for line in self.lines if line.name == wanted)

    def first(self, name: str) -> ContentLine | None:
        """This component's first content line named ``name``, or ``None``."""
        found = self.all_values(name)
        return found[0] if found else None


def parse_components(text: str) -> tuple[Component, ...]:
    """The top-level components ``text`` declares, nested children included.

    A component whose ``END`` never arrives is still returned, closed at the end of the
    feed. A truncated download is a real failure mode, and the events before the cut are
    real occupancy: discarding a whole timetable because its last event lost its ``END``
    would be a worse answer than keeping what parsed.

    Nesting past :data:`MAX_COMPONENT_DEPTH` is refused, naming the line. A feed is accepted up to
    the size bound, which is room for hundreds of thousands of ``BEGIN`` lines, and lexing all of
    them into a tree nothing can use is work done on a publisher's say-so. Refusing states the
    reason on the panel instead. The bound measures genuine NESTING: a repeated ``BEGIN`` closes the
    component of the same name it repeats, so a publisher that never closes its events is read
    rather than refused.
    """
    root = _OpenComponent(name="", line=0)
    stack = [root]
    for number, raw in unfold(text):
        line = parse_content_line(raw, number)
        if line is None:
            continue
        if line.name == _BEGIN:
            beginning = line.value.strip().upper()
            _close_unclosed_sibling(stack, beginning)
            _require_a_readable_depth(stack, number)
            stack.append(_OpenComponent(name=beginning, line=number))
        elif line.name == _END:
            _close(stack, line.value.strip().upper())
        else:
            stack[-1].lines.append(line)
    while len(stack) > 1:
        _close(stack, stack[-1].name)
    return tuple(root.children)


def _close_unclosed_sibling(stack: list[_OpenComponent], beginning: str) -> None:
    """Close the innermost open component when a ``BEGIN`` repeats its name.

    RFC 5545 defines no component that contains another of the same name, so a ``BEGIN:VEVENT``
    arriving while a ``VEVENT`` is open means the previous one lost its ``END`` rather than that the
    feed nests.

    Without this the depth bound counts siblings a publisher failed to close, which is neither what
    its name says nor what its message tells the publisher to look at, and a systematically
    unclosing feed is refused whole past the bound: exactly the answer the tolerance above exists to
    avoid.
    """
    if len(stack) > 1 and stack[-1].name == beginning:
        _close(stack, beginning)


def _require_a_readable_depth(stack: list[_OpenComponent], line: int) -> None:
    """Refuse a feed that nests deeper than syncr reads.

    The root frame is not a component, so the open count is one more than the nesting depth.
    """
    if len(stack) <= MAX_COMPONENT_DEPTH:
        return
    message = (
        f"the feed nests components more than {MAX_COMPONENT_DEPTH} deep, which is deeper than "
        "syncr will read"
    )
    raise MalformedValue(message, line=line)


def events_in(components: Sequence[Component]) -> Iterator[Component]:
    """Every ``VEVENT`` at any depth, in the order the feed declared them.

    Iterative, with an explicit stack, for the same reason :func:`parse_components` is: nesting
    depth is a property of a feed a third-party publisher controls, and a recursive walk turns a
    deeply nested body into a ``RecursionError``. That error is not an
    :class:`~syncr_api.calendars.ics_errors.IcsRejection`, so it would escape the adapter and
    break the one contract the whole module is built on.

    The stack is reversed on each push so children are visited in declaration order, which is the
    order a rejection's reported line has to agree with.
    """
    stack = list(reversed(components))
    while stack:
        component = stack.pop()
        if component.name == VEVENT:
            yield component
        stack.extend(reversed(component.children))


@dataclass(slots=True)
class _OpenComponent:
    """A component being built. Mutable, unlike what it becomes."""

    name: str
    line: int
    lines: list[ContentLine] = field(default_factory=list)
    children: list[Component] = field(default_factory=list)

    def closed(self) -> Component:
        return Component(
            name=self.name, lines=tuple(self.lines), children=tuple(self.children), line=self.line
        )


def _close(stack: list[_OpenComponent], name: str) -> None:
    """Close the innermost open component, tolerating a mismatched ``END``.

    A feed with an ``END`` naming an outer component closes everything up to and including
    it, which is what a publisher that dropped an inner ``END`` meant. An ``END`` naming
    nothing on the stack is ignored rather than discarding a component.
    """
    if len(stack) <= 1:
        return
    if all(open_component.name != name for open_component in stack[1:]):
        return
    while len(stack) > 1:
        finished = stack.pop()
        stack[-1].children.append(finished.closed())
        if finished.name == name:
            return


def _split_on_unquoted_colon(raw: str) -> tuple[str, str, str]:
    """``raw`` split at its first colon outside a quoted parameter value.

    A parameter value may be quoted and a quoted value may contain a colon, which is
    exactly what ``ALTREP="http://example.com/x":Title`` does. Splitting on the first colon
    would put the URL's scheme separator in the wrong half.
    """
    quoted = False
    for index, character in enumerate(raw):
        if character == '"':
            quoted = not quoted
        elif character == ":" and not quoted:
            return raw[:index], ":", raw[index + 1 :]
    return raw, "", ""


def _split_parameters(head: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    """The property name and its parameters, split on semicolons outside quotes."""
    parts = _split_on_unquoted(head, ";")
    name = parts[0].strip()
    params: list[tuple[str, str]] = []
    for part in parts[1:]:
        key, separator, value = part.partition("=")
        if not separator:
            continue
        params.append((key.strip().upper(), value.strip().strip('"')))
    return name, tuple(params)


def _split_on_unquoted(text: str, separator: str) -> list[str]:
    parts: list[str] = []
    quoted = False
    start = 0
    for index, character in enumerate(text):
        if character == '"':
            quoted = not quoted
        elif character == separator and not quoted:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts
