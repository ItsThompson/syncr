"""``EditEventRepository``: the training corpus, and the one write that grows it.

One method, and the base class is what states the rest of the contract. ``E5`` says edit events are
never pruned, so this extends :class:`~syncr_api.core.repository.TenantScopedReader`, which carries
no ``UPDATE`` and no ``DELETE`` builder at all: the rule is a shape rather than a sentence a future
reader has to find. A test reads this repository's whole public surface, inherited members included.

**``E1`` is the caller's to hold and this module's to make possible.** An event is written in the
same transaction as the pin that caused it, so the append takes no transaction of its own and opens
no session: a pin without its event would be a training label with no features, and the loss is
unrecoverable because the features are a fact about an instant that has passed.

**``E4``: an edit inside an off-plan span is recorded and flagged.** The flag is a field of the
stored context rather than a column, because it is a property of the edit's own circumstances
alongside the other twenty-odd features, and every fitter reads the context. Recorded rather than
refused, because a pin inside an off-plan span is exactly how "off, except this one thing" is
expressed: the edit is real and the exclusion is the learning layer's rule, not the writer's.

**``E2``: the objective delta is stored, never recomputed.** Nothing here recomputes one, and there
is no write that could: the only statement is an insert.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import insert

from syncr_api.core.repository import TenantScopedReader
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.plans.facts import EditEvent
from syncr_api.plans.stored_contexts import stored_context
from syncr_api.plans.stored_documents import stored_binding

if TYPE_CHECKING:
    from syncr_api.plans.declarations import EditToRecord
    from syncr_domain.identifiers import EditEventId


class EditEventRepository(TenantScopedReader):
    """One tenant's edit events. Appended, never changed, never removed."""

    async def append(self, edit: EditToRecord) -> EditEventId:
        """Record one pairwise preference, and answer with the row's id.

        The id is returned rather than the row: nothing in this deployment reads an event back, and
        answering with a record would be inventing a reader's shape. What the id buys is a log line
        that names the event a pin was written with, so the pair is traceable without a second read.
        """
        written = await self._session.scalars(
            insert(EditEvent)
            .values(
                [
                    {
                        "id": uuid4(),
                        TENANT_ID_COLUMN: self.tenant_id,
                        "iso_week": str(edit.iso_week),
                        "binding": stored_binding(edit.binding),
                        "proposed_starts_at": edit.proposed.start,
                        "proposed_ends_at": edit.proposed.end,
                        "accepted_starts_at": edit.accepted.start,
                        "accepted_ends_at": edit.accepted.end,
                        "objective_delta": edit.objective_delta,
                        "context": stored_context(edit.context),
                        "weight_set_version": edit.weight_set_version,
                        "created_at": edit.created_at,
                    }
                ]
            )
            .returning(EditEvent.id)
        )
        return written.one()
