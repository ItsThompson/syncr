"""The commitments a retained conflict names, read for the raise that records them.

``anchors`` holds facts, and two of them are what a repeated collision is stated over: the series a
recurring commitment belongs to, and the name the reader knows it by. A conflict is retained forever
and an anchor is not, so both are copied onto the row where the overlap is raised. That is the
reasoning ``plans.conflicts`` carries and this is the read that half of it needs.

**A second module beside the repository rather than a method on it**, because the caller is a
protocol declared in ``plans``: this class exists to satisfy that protocol, and putting a
``plans``-shaped answer on the general-purpose repository would put another package's vocabulary on
this one's storage surface.

**An anchor with no row is omitted rather than reported as absent-but-named.** The one caller stores
nulls for it, which is the honest record for an anchor whose feed stopped publishing it between an
assembly and the commit that raised against it. Omitting rather than raising is deliberate: a
solve's commit must not fail over a label.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syncr_api.anchors.models import Anchor
from syncr_api.core.repository import TenantScopedReader
from syncr_api.plans.conflicts import Commitment

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identifiers import AnchorId


class AnchorCommitments(TenantScopedReader):
    """One tenant's anchors, projected to what a conflict records about the commitment."""

    async def commitments(self, anchor_ids: Sequence[AnchorId]) -> Mapping[AnchorId, Commitment]:
        """The commitment each of these anchors is. Writes nothing.

        One statement for the whole set, because a raise records a handful of conflicts at once and
        a read per conflict would be a read per overlap on a solve's commit path. An empty request
        answers without a read: an empty ``IN`` already matches nothing, so this saves the round
        trip rather than changing the answer, and a week with no collision is the ordinary case.
        """
        if not anchor_ids:
            return {}
        rows = await self._session.scalars(
            self.scoped_select(Anchor).where(Anchor.id.in_(set(anchor_ids)))
        )
        return {row.id: Commitment(series_uid=row.series_uid, title=row.title) for row in rows}
