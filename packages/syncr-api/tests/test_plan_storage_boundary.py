"""Plan storage's structural rules: append-only, the three partial indexes, and the reads.

Four rules live here, and none of them can be enforced by a test of behavior.

**Append-only is a property of the class, not of its methods.** A repository that inherited
an ``UPDATE`` builder would expose a write path even if no method of its own called one, so the
rule is stated over the whole public surface, inherited members included.

**A document-describing column cannot be an argument.** If ``append`` accepted an
``iso_week``, a caller could store a revision under a week its document does not name, and
every read of that week would silently miss it. So the signature is asserted, not the write.

**The invariants that live in indexes have to be declared to exist.** The single-flight
solve, the one active weight set, and the one adjustment per kind and target are all
partial or unique indexes. The integration tier asserts each one BITES; this asserts each
one is declared, which is what fails when a later migration drops one.

**Every table needs the index its dominant query reads.** Storage growth is around 16 MB per
user-year, so nothing here is about size; what a missing index costs is a sequential scan on
the read path that runs most often.

Each rule is also run against something that breaks it, because a rule stated over twelve
tables that all pass says nothing about whether the reading works.
"""

from __future__ import annotations

import ast
import inspect
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Column, Index, MetaData, String, Table, Uuid

from syncr_api.core.columns import values_in
from syncr_api.core.orm import Base
from syncr_api.core.repository import TenantScopedReader, TenantScopedRepository
from syncr_api.core.tenancy import TENANT_ID_COLUMN
from syncr_api.idempotency.config import IDEMPOTENCY_KEYS_TABLE
from syncr_api.idempotency.models import IdempotencyKey  # noqa: F401 - registers its table
from syncr_api.learned.config import WEIGHT_SETS_TABLE
from syncr_api.learned.models import WeightSet  # noqa: F401 - registers its table
from syncr_api.plans.adjustments import WeekAdjustmentRepository
from syncr_api.plans.config import (
    ADJUSTMENT_KINDS,
    BLOCK_OUTCOMES_TABLE,
    CONFLICTS_TABLE,
    EDIT_EVENTS_TABLE,
    PENDING_PROPOSALS_TABLE,
    PINS_TABLE,
    PLAN_REVISIONS_TABLE,
    VERDICT_EVENTS_TABLE,
    WEEK_ADJUSTMENTS_TABLE,
    WEEK_INPUT_VERSIONS_TABLE,
)
from syncr_api.plans.models import PlanRevision  # noqa: F401 - registers the plan-side tables
from syncr_api.plans.proposals import PendingProposalRepository
from syncr_api.plans.repository import PlanRepository
from syncr_api.solving.config import NON_TERMINAL_STATUSES, OPERATIONS_TABLE, SOLVE
from syncr_api.solving.models import Operation  # noqa: F401 - registers its table
from tests.boundaries import package_mapped_classes, public_methods, table_names

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

# Names that say a method changes or removes a stored row. A repository over an append-only
# table must expose none of them, at any depth of its inheritance.
WRITING_VERBS = frozenset(
    {
        "update",
        "delete",
        "remove",
        "replace",
        "upsert",
        "set",
        "save",
        "clear",
        "drop",
        "patch",
        "modify",
        "revoke",
        "touch",
        "prune",
        "sweep",
        "purge",
        "expire",
    }
)

# The two things that are pruned, both telemetry rather than facts about a plan. Every other
# plan-side table is permanent: a review, a retro, a fitter, or a product metric reads it, and
# a fact not captured when it happened cannot be reconstructed.
PACKAGES_ALLOWED_A_RETENTION_PATH = frozenset({"idempotency", "solving"})
PRUNING_VERBS = frozenset({"prune", "sweep", "purge", "expire"})

PLAN_PACKAGES = ("plans", "solving", "learned", "idempotency")

# The read each table exists to serve, as the leading columns an index has to offer it. The
# subject set is derived from the packages themselves, so a table added later is either listed
# here or fails the completeness assertion below.
DOMINANT_READS: dict[str, tuple[tuple[str, ...], ...]] = {
    # The live plan, the churn baseline, and the projector's two-week range.
    PLAN_REVISIONS_TABLE: ((TENANT_ID_COLUMN, "iso_week"),),
    PENDING_PROPOSALS_TABLE: ((TENANT_ID_COLUMN, "iso_week"),),
    # The conditional write's `SELECT ... FOR UPDATE`.
    WEEK_INPUT_VERSIONS_TABLE: ((TENANT_ID_COLUMN, "iso_week"),),
    # The solve path reads the active set for a tenant.
    WEIGHT_SETS_TABLE: ((TENANT_ID_COLUMN,),),
    # The solver reads a week's pins as a hard constraint.
    PINS_TABLE: ((TENANT_ID_COLUMN, "iso_week"),),
    # A span of days for the ledger and the retro, and one outcome by its identity.
    BLOCK_OUTCOMES_TABLE: (
        (TENANT_ID_COLUMN, "occurred_at"),
        (TENANT_ID_COLUMN, "block_id", "revision_id"),
    ),
    # A fitter reads a window of edits, newest first.
    EDIT_EVENTS_TABLE: ((TENANT_ID_COLUMN, "created_at"),),
    CONFLICTS_TABLE: ((TENANT_ID_COLUMN, "iso_week"),),
    WEEK_ADJUSTMENTS_TABLE: ((TENANT_ID_COLUMN, "iso_week"),),
    # The metric job reads a period across every week in it.
    VERDICT_EVENTS_TABLE: ((TENANT_ID_COLUMN, "occurred_at"), (TENANT_ID_COLUMN, "iso_week")),
    # The week's operation for a client, the worker's claim, which serves every tenant, and
    # the retention sweep over one tenant's terminal rows.
    OPERATIONS_TABLE: (
        (TENANT_ID_COLUMN, "iso_week"),
        (TENANT_ID_COLUMN, "finished_at"),
        ("scheduled_for",),
    ),
    # A retry finds its key, and the sweep finds what this tenant has past its window.
    IDEMPOTENCY_KEYS_TABLE: (
        (TENANT_ID_COLUMN, "route", "idempotency_key"),
        (TENANT_ID_COLUMN, "expires_at"),
    ),
}


def index_column_lists(table: Table) -> list[list[str]]:
    """Every ordered column list this table offers a reader: its indexes and its key."""
    lists = [[column.name for column in index.columns] for index in table.indexes]
    if table.primary_key is not None:
        lists.append([column.name for column in table.primary_key.columns])
    return lists


def reads_without_an_index(table: Table, reads: Sequence[tuple[str, ...]]) -> list[str]:
    """The reads this table offers no index for."""
    offered = index_column_lists(table)
    return [
        f"{table.name} has no index leading with {list(leading)}"
        for leading in reads
        if not any(columns[: len(leading)] == list(leading) for columns in offered)
    ]


def named_index(table_name: str, index_name: str) -> Index:
    table = Base.metadata.tables[table_name]
    found = next((index for index in table.indexes if index.name == index_name), None)
    assert found is not None, f"{table_name} has no index named {index_name}"
    return found


def partial_predicate(index: Index) -> str:
    """The ``WHERE`` clause a partial index is declared with, as SQL."""
    return str(index.dialect_options["postgresql"].get("where", ""))


# --------------------------------------------------------------------------------
# Append-only, as a property of the class
# --------------------------------------------------------------------------------


def writing_members(repository: type) -> list[str]:
    """Public members of ``repository`` whose name says it changes a stored row.

    Every word of the name is read, not only the first: the write builders a base class
    contributes are ``scoped_update`` and ``scoped_delete``, and a check on the first word
    alone would find neither.
    """
    return sorted(
        name
        for name in dir(repository)
        if not name.startswith("_") and set(name.split("_")) & WRITING_VERBS
    )


def test_the_revision_repository_exposes_append_and_reads_and_nothing_else() -> None:
    assert public_methods(PlanRepository) == [
        "append",
        "find",
        "history",
        "latest",
        "latest_approved",
        # The inherited read builder. Every read above is composed from it, which is what puts
        # the tenant predicate on the statement rather than in each method.
        "scoped_select",
    ]


def test_the_revision_repository_inherits_no_way_to_change_a_row() -> None:
    # The half a method list cannot cover. `scoped_update` and `scoped_delete` build statements
    # over whatever model they are handed, so inheriting either would be an update path and a
    # delete path on the plan of record, whether or not a method of this class called one.
    assert writing_members(PlanRepository) == []
    assert not hasattr(PlanRepository, "scoped_update")
    assert not hasattr(PlanRepository, "scoped_delete")
    assert issubclass(PlanRepository, TenantScopedReader)
    assert not issubclass(PlanRepository, TenantScopedRepository)


def test_the_surface_check_reports_a_repository_that_could_change_a_row() -> None:
    # The control. Without it, "no write path" would pass on a reading that finds nothing, and
    # it would keep passing after someone changed the base class.
    class Mutable(TenantScopedRepository):
        pass

    assert writing_members(Mutable) == ["scoped_delete", "scoped_update"]
    assert writing_members(PendingProposalRepository) == [
        "clear",
        "replace",
        "scoped_delete",
        "scoped_update",
    ]


# --------------------------------------------------------------------------------
# A derived column cannot be an argument
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "write",
    [PlanRepository.append, PendingProposalRepository.replace],
    ids=["append", "replace"],
)
def test_a_document_writer_takes_no_week_of_its_own(write: object) -> None:
    assert callable(write)
    assert "iso_week" not in inspect.signature(write).parameters, (
        "the week is derived from the document being stored. Accepting one would let a "
        "revision be filed under a week its document does not name."
    )


def test_the_signature_check_reports_a_writer_that_does_take_one() -> None:
    # The control, and a real case rather than a synthetic one: an adjustment carries no
    # document, so its week has nowhere else to come from and is passed in.
    assert "iso_week" in inspect.signature(WeekAdjustmentRepository.upsert).parameters


# --------------------------------------------------------------------------------
# The invariants that live in indexes
# --------------------------------------------------------------------------------


def test_one_pending_proposal_per_week_is_the_primary_key() -> None:
    key = [column.name for column in Base.metadata.tables[PENDING_PROPOSALS_TABLE].primary_key]

    assert key == [TENANT_ID_COLUMN, "iso_week"], (
        "the single slot is the primary key, so a second proposal for a week is rejected by "
        "the database rather than by the upsert having been written correctly"
    )


def test_one_non_terminal_solve_per_week_is_a_partial_unique_index() -> None:
    index = named_index(OPERATIONS_TABLE, "uq_operations_tenant_id_iso_week_in_flight_solve")
    predicate = partial_predicate(index)

    assert index.unique is True
    assert [column.name for column in index.columns] == [TENANT_ID_COLUMN, "iso_week"]
    assert f"kind = '{SOLVE}'" in predicate
    for status in NON_TERMINAL_STATUSES:
        assert f"'{status}'" in predicate, predicate


def test_one_active_weight_set_per_tenant_is_a_partial_unique_index() -> None:
    index = named_index(WEIGHT_SETS_TABLE, "uq_weight_sets_tenant_id_active")

    assert index.unique is True
    assert [column.name for column in index.columns] == [TENANT_ID_COLUMN]
    assert partial_predicate(index) == "active"


def test_one_adjustment_per_week_kind_and_target_is_a_unique_index() -> None:
    index = named_index(
        WEEK_ADJUSTMENTS_TABLE, "uq_week_adjustments_tenant_id_iso_week_kind_target_id"
    )

    assert index.unique is True
    assert [column.name for column in index.columns] == [
        TENANT_ID_COLUMN,
        "iso_week",
        "kind",
        "target_id",
    ]


def test_one_outcome_per_block_and_revision_is_a_unique_index() -> None:
    index = named_index(BLOCK_OUTCOMES_TABLE, "uq_block_outcomes_tenant_id_block_id_revision_id")

    assert index.unique is True
    assert [column.name for column in index.columns] == [
        TENANT_ID_COLUMN,
        "block_id",
        "revision_id",
    ]


# --------------------------------------------------------------------------------
# The reads each table has to serve
# --------------------------------------------------------------------------------


def plan_side_tables(source_root: Path) -> set[str]:
    """Every table the plan-side packages declare, discovered rather than listed."""
    return table_names(
        model for package in PLAN_PACKAGES for model in package_mapped_classes(source_root, package)
    )


def test_every_plan_side_table_states_what_reads_it(source_root: Path) -> None:
    # An equality, not a containment: the subject is what the packages declare, so a table
    # added by a later ticket has to state what reads it, and an entry for a table that went
    # away has to go with it.
    declared = set(DOMINANT_READS)
    owned = plan_side_tables(source_root)

    assert declared == owned, {
        "states no read": sorted(owned - declared),
        "names no table": sorted(declared - owned),
    }


def test_the_table_walk_reads_the_whole_package_rather_than_one_module_of_it(
    source_root: Path,
) -> None:
    # The control for the subject set. `plans` declares three of its tables in `models.py` and
    # six in `facts.py`, so a walk that read one module per package would leave two thirds of
    # them outside the rule above, and the rule would go on passing once someone shortened the
    # list to match what the walk could see. Asserted as "more than one module contributes",
    # which is the property, rather than against a narrower walk that no longer exists.
    by_module: dict[str, set[str]] = {}
    for model in package_mapped_classes(source_root, "plans"):
        by_module.setdefault(model.__module__, set()).update(table_names([model]))

    assert set(by_module) == {"syncr_api.plans.models", "syncr_api.plans.facts"}
    assert PLAN_REVISIONS_TABLE in by_module["syncr_api.plans.models"]
    assert {BLOCK_OUTCOMES_TABLE, EDIT_EVENTS_TABLE, VERDICT_EVENTS_TABLE} <= by_module[
        "syncr_api.plans.facts"
    ]
    assert {BLOCK_OUTCOMES_TABLE, EDIT_EVENTS_TABLE, VERDICT_EVENTS_TABLE} <= plan_side_tables(
        source_root
    )


@pytest.mark.parametrize("table_name", sorted(DOMINANT_READS))
def test_the_table_offers_an_index_for_every_read_it_serves(table_name: str) -> None:
    table = Base.metadata.tables[table_name]

    assert reads_without_an_index(table, DOMINANT_READS[table_name]) == []


def test_the_index_check_reports_a_table_that_lacks_one() -> None:
    # The control, in a metadata of its own so it can never reach a migration.
    unindexed = Table(
        "unindexed_things",
        MetaData(),
        Column("tenant_id", Uuid(), nullable=False),
        Column("iso_week", String(8), nullable=False),
        Index("ix_unindexed_things_iso_week", "iso_week"),
    )

    assert reads_without_an_index(unindexed, ((TENANT_ID_COLUMN, "iso_week"),)) == [
        "unindexed_things has no index leading with ['tenant_id', 'iso_week']"
    ]


# --------------------------------------------------------------------------------
# The check-constraint helper the vocabularies are rendered by
# --------------------------------------------------------------------------------


def test_a_closed_vocabulary_renders_as_a_check_constraint() -> None:
    assert values_in("kind", ADJUSTMENT_KINDS) == (
        "kind IN ('drop_item', 'reduce_routine', 'breach_floor', 'accept_partial')"
    )


def test_a_vocabulary_member_carrying_a_quote_is_refused() -> None:
    # The members are rendered as literals rather than bound, which is safe because every
    # caller passes its own package's constants. A member carrying a quote would end the
    # string and whatever followed it would be read as SQL, so the rendering refuses one
    # rather than trusting every future caller to keep the convention.
    with pytest.raises(ValueError, match="carries a quote"):
        values_in("kind", ("drop_item", "') OR true --"))


# --------------------------------------------------------------------------------
# Retention: two paths, and no more
# --------------------------------------------------------------------------------


def pruning_methods(source_root: Path) -> dict[str, list[str]]:
    """Every method in a plan-side package whose name says it removes rows by age."""
    found: dict[str, list[str]] = {}
    for package in PLAN_PACKAGES:
        for module in sorted((source_root / package).glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            names = sorted(
                node.name
                for node in ast.walk(tree)
                if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
                and node.name.split("_")[0] in PRUNING_VERBS
            )
            if names:
                found.setdefault(package, []).extend(names)
    return found


def test_only_the_two_sanctioned_tables_have_a_retention_path(source_root: Path) -> None:
    found = pruning_methods(source_root)

    assert set(found) <= PACKAGES_ALLOWED_A_RETENTION_PATH, (
        f"{found}. Revisions, pins, outcomes, edit events, conflicts, adjustments and verdict "
        "events are facts about weeks that happened, and each is read by a review, a retro, a "
        "fitter, or a product metric. Only terminal operations and idempotency keys are pruned."
    )
    assert found == {"idempotency": ["sweep"]}, (
        f"{found}. The operations sweep arrives with the worker loop that runs it; until then "
        "the idempotency sweep is the only retention path in the product."
    )


def test_the_retention_walk_reads_the_packages_it_claims_to(source_root: Path) -> None:
    # The control for the walk's subject matter: a rule stated over four packages that resolved
    # to no files would pass forever.
    read = [
        module.name for package in PLAN_PACKAGES for module in (source_root / package).glob("*.py")
    ]

    assert "repository.py" in read
    assert len(read) >= len(PLAN_PACKAGES) * 2
    assert (source_root / "plans" / "repository.py").exists()


def test_the_retention_check_reports_a_prune_where_one_does_not_belong() -> None:
    source = "class PinRepository:\n    async def prune_old_pins(self) -> None: ...\n"
    tree = ast.parse(source)

    names = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name.split("_")[0] in PRUNING_VERBS
    ]

    assert names == ["prune_old_pins"]
