"""The one place a plan document's own columns come from, and the rule it enforces.

The document is authoritative and the scalar beside it exists so a week can be queried
without opening one. That only holds while no caller can set the scalar independently, which
is why the derivation is a function of the document and why no repository method takes an
``iso_week`` argument. This file is the derivation's own tests; the boundary suite asserts
that the signatures leave no way around it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import UnboundExecutionError
from sqlalchemy.ext.asyncio import AsyncSession

from syncr_api.plans.config import APPLIED, APPROVED
from syncr_api.plans.derivation import DOCUMENT_ISO_WEEK_KEY, derive_iso_week
from syncr_api.plans.errors import PlanDocumentRejected, RevisionRejected
from syncr_api.plans.repository import PlanRepository
from syncr_domain.weeks import IsoWeek

WEEK = IsoWeek(2026, 7)
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)


def test_the_week_is_read_from_the_document() -> None:
    assert derive_iso_week({DOCUMENT_ISO_WEEK_KEY: "2026-W07", "blocks": []}) == WEEK


def test_a_document_with_no_week_is_refused() -> None:
    # A row written from it would carry a week nobody chose, and every read of that week
    # would silently miss it.
    with pytest.raises(PlanDocumentRejected, match=DOCUMENT_ISO_WEEK_KEY):
        derive_iso_week({"blocks": []})


@pytest.mark.parametrize("value", [None, 7, ["2026-W07"], {"year": 2026}])
def test_a_week_that_is_not_a_string_is_refused(value: object) -> None:
    with pytest.raises(PlanDocumentRejected, match=DOCUMENT_ISO_WEEK_KEY):
        derive_iso_week({DOCUMENT_ISO_WEEK_KEY: value})


@pytest.mark.parametrize("value", ["2027-W53", "2026-W54", "2026-W00", "2026-W7", "nope", ""])
def test_a_week_that_names_no_iso_week_is_refused(value: str) -> None:
    # Parsed rather than copied, so the column cannot hold a week that does not exist.
    # `2027-W53` is the interesting one: it is well formed and 2027 has 52 weeks.
    with pytest.raises(PlanDocumentRejected):
        derive_iso_week({DOCUMENT_ISO_WEEK_KEY: value})


def test_a_week_at_the_year_boundary_is_accepted() -> None:
    # The control for the rejections above: 2026 genuinely has 53 ISO weeks, so a parser that
    # rejected week 53 outright would refuse a real week of a real year.
    assert derive_iso_week({DOCUMENT_ISO_WEEK_KEY: "2026-W53"}) == IsoWeek(2026, 53)


async def test_an_approved_revision_without_its_instant_is_refused_before_any_write() -> None:
    # PR2, in the repository. The database enforces the same pair, and the guard is what
    # names the invariant to the caller that broke it. The session here is unbound: the
    # guard has to raise before anything is added to it.
    repository = PlanRepository(AsyncSession(), uuid4())

    with pytest.raises(RevisionRejected, match="approved"):
        await repository.append(
            document={DOCUMENT_ISO_WEEK_KEY: str(WEEK)},
            objective_breakdown={},
            status=APPROVED,
            reason="user_approved",
            weight_set_version=1,
            input_version=1,
            created_at=NOW,
        )


async def test_the_guard_is_specific_to_the_approved_status() -> None:
    # The control. An applied revision has no instant of assent and must not be refused for
    # lacking one, so the guard is shown to distinguish rather than to reject every write.
    # Reaching the unbound session is the proof: the write got past the guard and failed for
    # want of a database, which is as far as this tier goes.
    repository = PlanRepository(AsyncSession(), uuid4())

    with pytest.raises(UnboundExecutionError):
        await repository.append(
            document={DOCUMENT_ISO_WEEK_KEY: str(WEEK)},
            objective_breakdown={},
            status=APPLIED,
            reason="auto_applied_fill",
            weight_set_version=1,
            input_version=1,
            created_at=NOW,
        )
