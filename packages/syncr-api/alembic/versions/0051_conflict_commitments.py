"""conflicts: the commitment a retained row names, so a repetition is computable across weeks

One change, and it closes the half of ``US-REV-05`` revision ``0039_conflicts`` could not.

**The commitment is denormalized onto the row.** The weekly session raises a repeated collision when
"the same anchor and the same binding have conflicted in three or more weeks". Revision
``0039_conflicts`` made the block half comparable by denormalizing ``binding``. The commitment half
was not comparable and had no equivalent fix at the time:

* ``anchor_id`` names one OCCURRENCE. A weekly standup publishes a distinct ``RECURRENCE-ID`` per
  week, so four weeks of collisions with one meeting hold four unrelated anchor ids.
* Worse, the row is usually gone. Reconciliation deletes an anchor its feed no longer publishes, and
  as the projection horizon rolls forward every past occurrence of a recurring commitment drops out
  of the feed, so the anchor a four-week-old conflict names has typically been deleted and its
  series cannot be read back from it.

So two columns:

| Column | Holds |
|---|---|
| ``series_uid`` | the publisher's own series key, or ``NULL`` for a one-off commitment |
| ``commitment_title`` | the commitment's name as it stood when the overlap was raised |

``series_uid`` is what a repetition GROUPS on, and ``NULL`` is a first-class answer rather than a
missing value: a commitment with no series cannot repeat, so such a row never contributes to a
repeated collision. ``commitment_title`` is what the raise NAMES, and it is denormalized for the
same reason ``binding`` is: the anchor row does not survive, and a label read from a deleted row is
no label at all.

Both are nullable, and the reason is not laxity. The raise site holds the commitment for every
overlap whose anchor still exists at the instant of the raise, which is every overlap in practice;
an anchor deleted between an assembly and the commit that raises against it genuinely has no
commitment to record, and a ``NOT NULL`` there would fail a solve's commit over a label. A row with
no title states the count without the name.

Existing rows are left alone. They read as commitments with no series, which is what "not comparable
across weeks" already meant for them, so no repetition is invented from a row that never carried the
key one is computed on.

Every literal below is spelled here rather than imported. A revision describes the schema at its own
point in the chain and is replayed forever against databases at that point, so a value read from the
workspace's live code would describe the schema as it is now instead.

Revision ID: 0051_conflict_commitments
Revises: 0042_pending_weights
Create Date: 2026-08-08

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Kept inside 32 characters, which is what `alembic_version.version_num` holds. Numbered for the
# ticket that adds it rather than sequentially: sibling tickets add a revision over disjoint tables
# in the same wave, so a shared counter would collide while the ticket number cannot.
revision: str = "0051_conflict_commitments"
down_revision: str | None = "0042_pending_weights"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "conflicts"
SERIES_UID = "series_uid"
COMMITMENT_TITLE = "commitment_title"

# The same widths `anchors` gives the two values this copies. Spelled rather than imported, for the
# reason the header states.
SERIES_UID_LENGTH = 512
TITLE_LENGTH = 500


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(SERIES_UID, sa.String(SERIES_UID_LENGTH), nullable=True))
    op.add_column(TABLE, sa.Column(COMMITMENT_TITLE, sa.String(TITLE_LENGTH), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, COMMITMENT_TITLE)
    op.drop_column(TABLE, SERIES_UID)
