"""What the control models publish about themselves.

``CONTROL_TABLES`` is what the rules that must never see a control table read, so it is asserted
against the models rather than against the metadata it is derived from: read off the same dict a
second time, the set would agree with itself whatever it held.
"""

from __future__ import annotations

from syncr_api.core.tenancy import TENANTS_TABLE
from tests.control_models import CONTROL_TABLES, ControlBase, ScopedThing, UnscopedThing


def test_the_control_table_set_names_every_control_model() -> None:
    assert {ScopedThing.__tablename__, UnscopedThing.__tablename__} == CONTROL_TABLES


def test_the_control_table_set_leaves_out_the_borrowed_identity_table() -> None:
    # `tenants` is in this metadata so a control table's foreign key resolves. Naming it a
    # control table would tell the rules that read this set that the application's own table
    # is one of these, and the first of those rules asserts none of them is in `Base.metadata`.
    assert TENANTS_TABLE in ControlBase.metadata.tables
    assert TENANTS_TABLE not in CONTROL_TABLES
