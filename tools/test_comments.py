"""What counts as prose, in both directions, for every comment spelling the reading knows.

A test here plants the exact form the reading has to get right and asserts what came back, because
each of these forms defeated one line-matching version of this reading: a comment after code on the
same line, a rule name a fixture passes as a value, and a comment marker inside a quoted string.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import comments
from invariant_labels import REPO_ROOT, tracked


def pieces(name: str, text: str) -> list[str]:
    """The prose the reading finds in ``text``, read as the file ``name`` would be."""
    return [piece for _, piece in comments.prose(Path(name), text)]


class TestPython:
    def test_a_comment_after_code_on_the_same_line_is_prose(self) -> None:
        assert pieces("x.py", "value = 1  # what the value is for\n") == ["# what the value is for"]

    def test_an_indented_comment_is_prose(self) -> None:
        assert pieces("x.py", "def f():\n    # why\n    return 1\n") == ["# why"]

    def test_a_docstring_is_prose_and_carries_its_own_line(self) -> None:
        found = list(comments.prose(Path("x.py"), 'def f():\n    """What f does."""\n'))

        assert found == [(2, "What f does.")]

    def test_a_stand_alone_string_in_a_body_is_prose(self) -> None:
        """The form a comment takes when someone wants a paragraph rather than hash lines."""
        text = 'def f():\n    x = 1\n    """A note about x."""\n    return x\n'

        assert pieces("x.py", text) == ["A note about x."]

    def test_a_string_passed_as_an_argument_is_not_prose(self) -> None:
        """The shape that makes a value indistinguishable from a citation to a line-matcher."""
        assert pieces("x.py", 'record(rule="ZZ4", detail="why")\n') == []

    def test_a_string_assigned_to_a_name_is_not_prose(self) -> None:
        assert pieces("x.py", 'RULE = "ZZ4"\n') == []

    def test_a_file_that_does_not_parse_refuses_rather_than_reading_nothing(self) -> None:
        """A silent skip here would report a clean file for a file it never read."""
        with pytest.raises(comments.Unreadable, match=r"x\.py does not read as \.py"):
            pieces("x.py", "def f(:\n")


class TestTheSlashLanguages:
    def test_a_line_comment_is_prose(self) -> None:
        assert pieces("x.ts", "const a = 1; // why a\n") == ["// why a"]

    def test_a_marker_inside_a_string_is_not_a_comment(self) -> None:
        """A URL is the form that made a line-matching reading read half a string as prose."""
        assert pieces("x.ts", 'const at = "https://example.test/a";\n') == []

    def test_a_block_comment_is_prose_and_carries_the_line_it_opened_on(self) -> None:
        found = list(comments.prose(Path("x.tsx"), "a;\n/* one\n   two */\nb;\n"))

        assert found == [(2, "/* one\n   two */")]

    def test_a_comment_after_a_block_comment_is_still_read(self) -> None:
        """The line count has to survive a block comment or every later line is misreported."""
        found = list(comments.prose(Path("x.ts"), "/* one\n   two */\nb; // after\n"))

        assert found == [(1, "/* one\n   two */"), (3, "// after")]

    def test_a_template_literal_may_hold_lines_without_hiding_what_follows(self) -> None:
        found = pieces("x.ts", "const a = `\n// inside a value\n`;\n// after\n")

        assert found == ["// after"]

    def test_a_css_block_comment_is_prose(self) -> None:
        assert pieces("x.css", ".a { /* why */ }\n") == ["/* why */"]


class TestTheHashLanguages:
    def test_a_comment_is_prose(self) -> None:
        assert pieces("x.yml", "# why\nkey: value\n") == ["# why"]

    def test_a_marker_inside_a_quoted_value_is_not_a_comment(self) -> None:
        assert pieces("x.yml", 'key: "a # b"\n') == []

    def test_an_unclosed_quote_does_not_hide_the_rest_of_the_file(self) -> None:
        """A value ends at its line, so one apostrophe cannot make every later comment invisible."""
        assert pieces("justfile", "recipe:\n    echo it's\n# after\n") == ["# after"]

    def test_a_sql_comment_is_prose(self) -> None:
        assert pieces("x.sql", "select 1; -- why\n") == ["-- why"]


class TestThePartition:
    def test_every_kind_of_file_the_index_holds_is_declared(self) -> None:
        """A kind in neither table is a file type nobody decided about.

        Which is how a tree comes to be unread while a census over it reports clean.
        """
        assert comments.undeclared(tracked(REPO_ROOT)) == []

    def test_a_kind_in_neither_table_is_reported(self) -> None:
        assert comments.undeclared([Path("a/b.rs")]) == [".rs"]

    def test_every_skipped_kind_states_why(self) -> None:
        assert [kind for kind, reason in comments.SKIPPED.items() if not reason.strip()] == []

    def test_no_kind_is_both_read_and_skipped(self) -> None:
        assert set(comments.READ) & set(comments.SKIPPED) == set()
