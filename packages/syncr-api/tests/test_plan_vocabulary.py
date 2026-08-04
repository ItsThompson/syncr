"""The plan-side vocabularies, stated in two packages, asserted to be one set.

``syncr_domain.plan`` owns the document's vocabularies, because the document is a domain value
and the storage layer holds only its JSONB column. ``syncr_api.plans.config`` holds what the
tables are defined against: the tuple a check constraint renders, the ``Literal`` a repository
signature narrows a caller with, and the width of the column a block id is stored in.

The tuple and the width are now taken from the domain rather than written twice. What cannot be
derived is the ``Literal``, because a type cannot be built from an enum at type-check time, so
the two statements of the revision reasons are compared here, in the one package that can see
both. Without this, a seventh reason added to either side would leave a row the database
accepts and no reader knows, or a reason a caller can pass and no row can hold.

The same argument applies to the block id's width from the other end: the derivation produces a
full SHA-256 in hex, and a column narrower than that would truncate an identity two mechanisms
pair on.
"""

from __future__ import annotations

from typing import get_args
from uuid import uuid4

from syncr_api.plans.config import BLOCK_ID_MAX_LENGTH, REVISION_REASONS, RevisionReason
from syncr_domain.identity import BLOCK_ID_LENGTH, BindingRef, block_id
from syncr_domain.plan import RevisionReason as DocumentRevisionReason
from syncr_domain.weeks import IsoWeek


def test_the_stored_vocabulary_and_the_document_vocabulary_are_the_same_set() -> None:
    assert set(REVISION_REASONS) == {reason.value for reason in DocumentRevisionReason}


def test_the_narrowing_a_repository_applies_is_the_same_set_too() -> None:
    """The one statement that cannot be derived, so it is the one that has to be compared."""
    assert set(get_args(RevisionReason.__value__)) == {
        reason.value for reason in DocumentRevisionReason
    }


def test_the_constraint_reads_the_reasons_in_the_documents_own_order() -> None:
    """So a rejection message and the enum list the members the same way."""
    assert list(REVISION_REASONS) == [reason.value for reason in DocumentRevisionReason]


def test_the_column_holds_exactly_what_the_derivation_produces() -> None:
    """A column narrower than the digest would truncate an identity two mechanisms pair on."""
    derived = block_id(IsoWeek(2026, 7), BindingRef.for_anchor(uuid4()))

    assert BLOCK_ID_MAX_LENGTH == BLOCK_ID_LENGTH == len(derived)
