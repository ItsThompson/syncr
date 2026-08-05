"""Fixtures every test in this suite needs, and the one safety property it must not lose.

**No test may reach the machine's real keychain.** ``keyring`` resolves a process-global backend,
so a test that stored a token would write to the developer's login keychain and a test that read
one could prompt for a password. The autouse fixture installs an in-memory backend for every test
and restores whatever was there afterwards, so the suite is hermetic by default and a test that
wants the no-keychain machine asks for it explicitly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import keyring
import pytest

from tests.keyrings import InMemoryKeyring

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(autouse=True)
def in_memory_keychain() -> Iterator[InMemoryKeyring]:
    """A keychain that lives for one test and touches nothing outside the process."""
    previous = keyring.get_keyring()
    backend = InMemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)
