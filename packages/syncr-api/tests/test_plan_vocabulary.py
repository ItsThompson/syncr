"""The plan-side vocabularies, stated in two packages, asserted to be one set.

``syncr_domain.plan`` owns the document's vocabularies, because the document is a domain value
and the storage layer holds only its JSONB column. ``syncr_api.plans.config`` holds what the
tables are defined against: the tuple a check constraint renders, the ``Literal`` a repository
signature narrows a caller with, and the width of the column a block id is stored in.

**Two of these four tests cannot fail today, and that is what they are for.** The tuple and the
width are derived from the domain rather than written twice, so drift between them is not
representable and no test can detect it. What they detect is the derivation being replaced by a
literal: the day someone writes the six strings out again, these turn red on the first divergence.

The two that bite now are the other two. The ``Literal`` cannot be derived, because a type cannot
be built from an enum at type-check time, so it is a genuine second statement and it is compared
here, in the one package that can see both. And the column's width is a number the migration
spells for itself, so a shortened digest or a widened column shows up as an inequality.
"""

from __future__ import annotations

from typing import get_args
from uuid import uuid4

from syncr_api.plans.config import BLOCK_ID_MAX_LENGTH, REVISION_REASONS, RevisionReason
from syncr_domain.identity import BLOCK_ID_LENGTH, BindingRef, block_id
from syncr_domain.plan import RevisionReason as DocumentRevisionReason
from syncr_domain.weeks import IsoWeek


def test_the_constraints_vocabulary_is_the_documents_own_rather_than_a_copy_of_it() -> None:
    """A regression guard, not a drift detector.

    `REVISION_REASONS` is a comprehension over the domain enum, so this compares that
    comprehension to itself and passes whatever the enum holds, including a reordering. It earns
    its place by failing the day the comprehension becomes a literal that has drifted.
    """
    assert set(REVISION_REASONS) == {reason.value for reason in DocumentRevisionReason}


def test_the_constraint_lists_the_reasons_in_the_documents_own_order() -> None:
    """The same guard, over order rather than membership, and for the same reason.

    Order matters to a reader of a rejection message rather than to the constraint. This cannot
    detect a reordering of the enum either: the tuple follows it.
    """
    assert list(REVISION_REASONS) == [reason.value for reason in DocumentRevisionReason]


def test_the_narrowing_a_repository_applies_is_the_same_set() -> None:
    """The one statement that cannot be derived, so it is the one that has to be compared.

    Measured: adding a seventh reason to the domain enum, or renaming one, fails here and nowhere
    else in this file.
    """
    assert set(get_args(RevisionReason.__value__)) == {
        reason.value for reason in DocumentRevisionReason
    }


def test_the_column_holds_exactly_what_the_derivation_produces() -> None:
    """A column narrower than the digest would truncate an identity two mechanisms pair on.

    Measured: shortening the digest fails here even when the width constant is left at 64, which
    is the case a comparison of the two constants alone would miss.
    """
    derived = block_id(IsoWeek(2026, 7), BindingRef.for_anchor(uuid4()))

    assert BLOCK_ID_MAX_LENGTH == BLOCK_ID_LENGTH == len(derived)
