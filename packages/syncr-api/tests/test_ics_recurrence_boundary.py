"""The grammar and expansion modules meet on one canonical recurrence rule."""

from __future__ import annotations

import pytest

from syncr_api.calendars.ics_errors import UnparseableRecurrence
from syncr_api.calendars.ics_recurrence_expansion import _parsed_rule
from syncr_api.calendars.ics_recurrence_grammar import _parse_rule


@pytest.mark.parametrize("whitespace", [" ", "\t", "\n", "\u2003"])
def test_the_grammar_rejects_every_whitespace_character_dateutil_split_would_read(
    whitespace: str,
) -> None:
    with pytest.raises(UnparseableRecurrence, match="whitespace"):
        _parse_rule(f"FREQ=DAILY{whitespace}INTERVAL=1")


def test_the_expander_docstring_names_the_dateutil_branch_unfold_uses() -> None:
    assert _parsed_rule.__doc__ is not None
    assert "does not call ``str.split()``" in _parsed_rule.__doc__
