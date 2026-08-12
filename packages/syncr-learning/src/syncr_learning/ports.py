"""What the run reads and writes, as two protocols. The whole of this job's I/O surface.

Declared here rather than imported, so every module above this one depends on the OPERATIONS the run
performs and not on a database. A test drives the run against lists, which is what makes the
idempotence claim and the exit-code rule checkable without Postgres.

**The writer has one method, and there is no update and no delete.** Each run APPENDS a new version
rather than mutating the current one, so comparison and rollback are free and a revert is a flag. A
protocol with an update method would be a shape in which a run could rewrite history.

**Nothing here can reach ``plan_revisions``, ``pins`` or ``block_outcomes`` as a writer.** The
learning layer is a reader of facts and a writer of parameters, and the absence of the method is the
enforcement: there is no call for a module above to make.

The repeated-pin candidates a run finds are returned rather than written. The rows the weekly
session reads, and the accept and decline routes over them, are the promotion surface's own; a table
this job wrote and nothing read would be the number-nobody-reads this package exists to avoid.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from syncr_domain.identifiers import TenantId
    from syncr_learning.artifact import FittedWeightSet
    from syncr_learning.facts import TenantCorpus


class CorpusReader(Protocol):
    """Everything the run reads. Four reads, none of them a write."""

    async def tenants(self) -> Sequence[TenantId]:
        """Every tenant this deployment holds, in a stable order."""
        ...

    async def corpus(self, tenant_id: TenantId) -> TenantCorpus:
        """One tenant's revisions, outcomes, edits, pins and off-plan spans."""
        ...

    async def weights_in_force(self, tenant_id: TenantId) -> Mapping[str, float] | None:
        """The seven term weights the active version carries, or nothing because there is none.

        ``None`` is a tenant with no active weight set, which provisioning makes unreachable. A run
        that meets one refuses to fit weights for it rather than inventing an incumbent to beat.
        """
        ...

    async def area_names(self, tenant_id: TenantId) -> Mapping[str, str]:
        """Each Area's own name by its identifier, for the plain-language statements.

        The sentence the user reads has to name the Area they named. A statement keyed on a UUID
        would be a diagnostic line, which is the one thing the Learned screen is not.
        """
        ...


class ParameterWriter(Protocol):
    """Everything the run writes: a new weight-set version, and the promotions to raise."""

    async def append_version(self, tenant_id: TenantId, fitted: FittedWeightSet) -> int:
        """Append a new version for this tenant and answer with the version number.

        The new row is NOT active. Activation is a user-facing act with a re-solve behind it, and it
        belongs to the screen that offers it: a nightly job that activated its own output would move
        the plan under the user overnight.
        """
        ...
