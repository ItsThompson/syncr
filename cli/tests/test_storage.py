"""Where the refresh token goes, and what happens on a machine with no keychain.

The properties under test are properties about a secret. The keychain is used when there is one.
The fallback is a file created 0600 and replaced atomically. The downgrade is stated out loud.
Nothing reads a credential from the environment.
"""

from __future__ import annotations

import json
import os
import stat
from io import StringIO
from pathlib import Path

import keyring
import pytest

from syncr_cli.auth.storage import (
    KEYCHAIN_LOCATION,
    KEYRING_SERVICE,
    RefreshTokenStore,
    credentials_path,
)
from syncr_cli.notices import Notices
from tests.keyrings import InMemoryKeyring, NoKeychain

ACCOUNT = "https://syncr.example"
TOKEN = "syncrr_the_refresh_token"  # pragma: allowlist secret
SECOND_TOKEN = "syncrr_the_rotated_one"  # pragma: allowlist secret


@pytest.fixture
def notices() -> Notices:
    return Notices(StringIO())


def store(tmp_path: Path, notices: Notices) -> RefreshTokenStore:
    return RefreshTokenStore(
        account=ACCOUNT, file_path=tmp_path / "credentials.json", notices=notices
    )


def test_the_keychain_holds_the_token_when_there_is_one(
    tmp_path: Path, notices: Notices, in_memory_keychain: InMemoryKeyring
) -> None:
    keeping = store(tmp_path, notices)

    keeping.write(TOKEN)

    assert keeping.read() == TOKEN
    assert in_memory_keychain.stored[(KEYRING_SERVICE, ACCOUNT)] == TOKEN
    assert keeping.location == KEYCHAIN_LOCATION
    assert keeping.fell_back is False
    assert notices.stated == ()
    assert not (tmp_path / "credentials.json").exists()


def test_a_machine_with_no_keychain_falls_back_and_says_so(
    tmp_path: Path, notices: Notices
) -> None:
    # A silent downgrade of secret storage is worse than a loud one, so the notice is the assertion
    # as much as the file is.
    keyring.set_keyring(NoKeychain())
    keeping = store(tmp_path, notices)

    keeping.write(TOKEN)

    assert keeping.read() == TOKEN
    assert keeping.fell_back is True
    assert keeping.location == str(tmp_path / "credentials.json")
    assert len(notices.stated) == 1
    stated = notices.stated[0]
    assert KEYCHAIN_LOCATION in stated
    assert "0600" in stated
    assert str(tmp_path / "credentials.json") in stated


def test_the_fallback_file_is_created_readable_by_nobody_else(
    tmp_path: Path, notices: Notices
) -> None:
    keyring.set_keyring(NoKeychain())

    store(tmp_path, notices).write(TOKEN)

    mode = stat.S_IMODE(os.stat(tmp_path / "credentials.json").st_mode)
    assert mode == 0o600


def test_the_fallback_states_its_downgrade_once_however_often_it_is_used(
    tmp_path: Path, notices: Notices
) -> None:
    keyring.set_keyring(NoKeychain())
    keeping = store(tmp_path, notices)

    keeping.write(TOKEN)
    keeping.read()
    keeping.write(SECOND_TOKEN)

    assert len(notices.stated) == 1


def test_a_rotation_replaces_the_stored_token_rather_than_keeping_both(
    tmp_path: Path, notices: Notices
) -> None:
    # Presenting a consumed refresh token revokes the whole family, so a store that kept the
    # predecessor would eventually present it.
    keeping = store(tmp_path, notices)

    keeping.write(TOKEN)
    keeping.write(SECOND_TOKEN)

    assert keeping.read() == SECOND_TOKEN


def test_two_deployments_do_not_overwrite_each_others_credential(
    tmp_path: Path, notices: Notices
) -> None:
    keyring.set_keyring(NoKeychain())
    one = RefreshTokenStore(
        account="https://one.example", file_path=tmp_path / "credentials.json", notices=notices
    )
    two = RefreshTokenStore(
        account="https://two.example", file_path=tmp_path / "credentials.json", notices=notices
    )

    one.write(TOKEN)
    two.write(SECOND_TOKEN)

    assert one.read() == TOKEN
    assert two.read() == SECOND_TOKEN


def test_clearing_removes_the_token_from_both_stores(tmp_path: Path, notices: Notices) -> None:
    # A machine that fell back once may hold a copy in the file while the keychain works today, and
    # a logout that left either behind would leave a credential the user believes they revoked.
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({ACCOUNT: TOKEN}), encoding="utf-8")
    keeping = store(tmp_path, notices)
    keeping.write(SECOND_TOKEN)

    keeping.clear()

    assert keeping.read() is None
    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_clearing_a_machine_that_holds_nothing_is_not_a_failure(
    tmp_path: Path, notices: Notices
) -> None:
    store(tmp_path, notices).clear()


def test_a_corrupt_credential_file_reads_as_holding_nothing(
    tmp_path: Path, notices: Notices
) -> None:
    # The recovery is to authorize again. Refusing every command until a file is deleted by hand
    # would be a worse answer than replacing it.
    keyring.set_keyring(NoKeychain())
    path = tmp_path / "credentials.json"
    path.write_text("not json at all", encoding="utf-8")
    keeping = store(tmp_path, notices)

    assert keeping.read() is None

    keeping.write(TOKEN)
    assert keeping.read() == TOKEN


def test_no_partial_file_is_left_when_a_write_cannot_finish(
    tmp_path: Path, notices: Notices, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The write is a temporary file plus a rename, so an interrupted one leaves the previous
    # credential where it was rather than half of the new one.
    keyring.set_keyring(NoKeychain())
    keeping = store(tmp_path, notices)
    keeping.write(TOKEN)

    def refuse(_source: object, _destination: object) -> None:
        raise OSError("the disk went away")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError, match="disk went away"):
        keeping.write(SECOND_TOKEN)

    monkeypatch.undo()
    assert keeping.read() == TOKEN
    assert list(tmp_path.glob(".credentials-*")) == []


def test_the_credential_files_own_permissions_are_stated_when_they_are_broader(
    tmp_path: Path, notices: Notices
) -> None:
    # A file this store did not write may be anything. The discipline is that a secret-storage
    # property is announced rather than inferred, so "the file was NOT 0600" is announced too.
    keyring.set_keyring(NoKeychain())
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps({ACCOUNT: TOKEN}), encoding="utf-8")
    path.chmod(0o644)

    assert store(tmp_path, notices).read() == TOKEN

    stated = " ".join(notices.stated)
    assert "0644" in stated
    assert str(path) in stated
    assert "chmod 600" in stated


def test_a_file_at_the_right_mode_says_nothing_about_it(tmp_path: Path, notices: Notices) -> None:
    # The other direction, so the notice discriminates rather than always firing.
    keyring.set_keyring(NoKeychain())
    keeping = store(tmp_path, notices)
    keeping.write(TOKEN)
    before = len(notices.stated)

    assert keeping.read() == TOKEN
    assert len(notices.stated) == before


def test_the_credentials_file_sits_beside_the_configuration_rather_than_inside_it() -> None:
    # A configuration file is one a user edits and pastes. A credential must not be in it.
    path = credentials_path(Path("/home/someone/.config/syncr/config.toml"))

    assert path == Path("/home/someone/.config/syncr/credentials.json")
