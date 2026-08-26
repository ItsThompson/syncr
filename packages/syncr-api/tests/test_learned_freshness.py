"""The freshness rule for the two strings a learned row says about one Area.

A row's sentence is frozen at fit time and its subject resolves at read time, so a rename moves
one string and not the other. These tests rename an Area and assert what each string says
afterwards: the assertions are the record of the rule, so a future change to either lifetime
reddens here rather than drifting onto the screen.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from syncr_api.learned.maturity import maturity_rows
from syncr_api.learned.subjects import subject_of

FITNESS = uuid4()

# One keyed row, as the fitter writes it: the sentence already carries the name the fit knew.
STORED: tuple[dict[str, object], ...] = (
    {
        "parameter": f"duration_multiplier[{FITNESS}]",
        "samples": 14,
        "threshold": 12,
        "state": "ready",
        "value": 1.37,
        "shrinkage_weight": 0.42,
        "plain_language": "You estimate 60m for Fitness; your actual median is 82m.",
    },
)

BEFORE = {FITNESS: "Fitness"}
AFTER_THE_RENAME = {FITNESS: "Climbing"}


class TestARenameMovesTheSubjectAndNotTheSentence:
    def test_before_the_rename_both_strings_say_the_same_area(self) -> None:
        row = maturity_rows(STORED)[0]
        assert subject_of(row.parameter, BEFORE) == "Fitness"
        assert "Fitness" in row.plain_language

    def test_after_the_rename_the_subject_says_the_name_the_tenant_holds_now(self) -> None:
        row = maturity_rows(STORED)[0]
        assert subject_of(row.parameter, AFTER_THE_RENAME) == "Climbing"

    def test_after_the_rename_the_sentence_still_says_the_name_it_was_fitted_under(self) -> None:
        # The stored document is re-read unchanged: the rename lives only in the tenant's Areas.
        row = maturity_rows(STORED)[0]
        assert "Fitness" in row.plain_language
        assert "Climbing" not in row.plain_language

    def test_rereading_the_same_document_changes_neither_string(self) -> None:
        # Freshness is decided by the mapping handed in, never by the stored row itself.
        assert maturity_rows(STORED) == maturity_rows(STORED)


def test_the_sentence_survives_a_rename_because_nothing_rewrites_storage() -> None:
    renamed: dict[UUID, str] = {FITNESS: "Climbing"}
    row_before = maturity_rows(STORED)[0]
    row_after = maturity_rows(STORED)[0]
    assert row_after.plain_language == row_before.plain_language
    assert subject_of(row_after.parameter, renamed) == "Climbing"
