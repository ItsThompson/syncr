"""The frozen view the decline repository returns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from syncr_domain.identifiers import TenantId


@dataclass(frozen=True, slots=True)
class PromotionDeclineRecord:
    """One declined candidate, as stored.

    ``promotion_id`` is ``PromotionRef.id`` rather than a parsed reference. A stored value that no
    longer parses -- a kind removed from the enum, say -- should suppress the question it was
    written about and otherwise say nothing, and a record that refused to be read would fault the
    whole session instead.
    """

    tenant_id: TenantId
    promotion_id: str
    declined_at: datetime
    suppressed_until: datetime
