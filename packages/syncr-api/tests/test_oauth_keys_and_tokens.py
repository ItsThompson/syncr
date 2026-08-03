"""The signing keys: rotation, encryption at rest, the JWKS, and the audience binding.

Four properties are asserted here, and each one is a live-token outage or a credential leak if
it breaks.

Rotation keeps the previous key, so a token signed a moment before a rotation still verifies.
The published key set carries public material only. The file on disk is ciphertext, and the
wrong key cannot read it. And an access token is bound to this API's audience, so a token for
any other audience is refused.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import jwt
import pytest
from cryptography.fernet import Fernet

from syncr_api.core.scopes import ALL_SCOPES, Scope
from syncr_api.core.settings import (
    DEV_OAUTH_KEY_ENCRYPTION_KEY,
    EnvSettings,
    build_service_settings,
)
from syncr_api.oauth.access_tokens import AccessTokenCodec
from syncr_api.oauth.config import ACCESS_TOKEN_LIFETIME, OAuthConfig, build_oauth_config
from syncr_api.oauth.keys import (
    SIGNING_ALGORITHM,
    SigningKeySet,
    generate_signing_key,
    load_signing_key_set,
    read_key_file,
    rotate,
    write_key_file,
)
from syncr_api.oauth.metadata import build_metadata
from syncr_api.oauth.rotation import rotate_signing_keys

if TYPE_CHECKING:
    from pathlib import Path

ISSUER = "https://syncr.example"
AUDIENCE = "https://syncr.example/api/v1"
OTHER_AUDIENCE = "https://mcp.syncr.example"
NOW = datetime(2026, 2, 9, 9, 0, tzinfo=UTC)

ENCRYPTION_KEY = "dGVzdC1vbmx5LW9hdXRoLWtleS1lbmNyeXB0aW9uLWs="  # pragma: allowlist secret
OTHER_ENCRYPTION_KEY = "YW5vdGhlci1kZXBsb3ltZW50cy1lbmNyeXB0aW9uLWs="  # pragma: allowlist secret


def codec_for(keys: SigningKeySet, *, audience: str = AUDIENCE) -> AccessTokenCodec:
    return AccessTokenCodec(keys, issuer=ISSUER, audience=audience)


@pytest.fixture
def keys() -> SigningKeySet:
    return SigningKeySet(current=generate_signing_key("first"))


# --- Rotation and the JWKS -------------------------------------------------------------


def test_rotation_retires_the_current_key_rather_than_dropping_it(keys: SigningKeySet) -> None:
    rotated = rotate(keys)

    assert rotated.current.kid != keys.current.kid
    assert rotated.previous is not None
    assert rotated.previous.kid == keys.current.kid


def test_a_token_signed_before_a_rotation_still_verifies_after_it(keys: SigningKeySet) -> None:
    # The whole reason two keys are held. If this fails, every deploy that rotates signs out
    # every client holding a live token.
    minted = codec_for(keys).mint(
        tenant_id=uuid4(),
        user_id=uuid4(),
        client_id="syncr-cli",
        scopes=ALL_SCOPES,
        issued_at=NOW,
    )

    after = codec_for(rotate(keys))

    assert after.verify(minted.token, at=NOW) is not None


def test_a_token_signed_two_rotations_ago_no_longer_verifies(keys: SigningKeySet) -> None:
    # The control for the assertion above, and the stated limit of the guarantee: the JWKS
    # publishes two keys, not a history.
    minted = codec_for(keys).mint(
        tenant_id=uuid4(),
        user_id=uuid4(),
        client_id="syncr-cli",
        scopes=ALL_SCOPES,
        issued_at=NOW,
    )

    after_two = codec_for(rotate(rotate(keys)))

    assert after_two.verify(minted.token, at=NOW) is None


def test_the_first_rotation_of_a_new_deployment_retires_nothing() -> None:
    assert rotate(None).previous is None


def test_the_published_key_set_carries_both_keys_and_no_private_material(
    keys: SigningKeySet,
) -> None:
    published = rotate(keys).jwks()

    assert [key["kid"] for key in published["keys"]] != []
    assert len(published["keys"]) == 2
    for key in published["keys"]:
        assert key["kty"] == "EC"
        assert key["alg"] == SIGNING_ALGORITHM
        assert key["use"] == "sig"
        # `d` is the private scalar. Its presence would publish the ability to mint.
        assert "d" not in key, "the JWKS published private key material"
        assert {"x", "y"} <= set(key)


def test_the_published_key_set_is_what_a_verifier_can_actually_use(keys: SigningKeySet) -> None:
    # Not a shape assertion: the published document is parsed back into a key and used to
    # verify a real token, which is what an MCP resource server will do in P1.
    minted = codec_for(keys).mint(
        tenant_id=uuid4(),
        user_id=uuid4(),
        client_id="syncr-cli",
        scopes=frozenset({Scope.PLAN_READ}),
        issued_at=NOW,
    )
    published = keys.jwks()["keys"][0]

    verified = jwt.decode(
        minted.token,
        jwt.PyJWK.from_dict(published).key,
        algorithms=[SIGNING_ALGORITHM],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"verify_exp": False},
    )

    assert verified["scope"] == Scope.PLAN_READ.value


# --- Encryption at rest ----------------------------------------------------------------


def test_the_key_file_on_disk_is_ciphertext(tmp_path: Path, keys: SigningKeySet) -> None:
    path = tmp_path / "keys.enc"

    write_key_file(path, ENCRYPTION_KEY, keys)

    written = path.read_bytes()
    assert keys.current.kid.encode() not in written
    assert b"P-256" not in written
    assert b'"d"' not in written


def test_the_key_file_is_owner_readable_only(tmp_path: Path, keys: SigningKeySet) -> None:
    path = tmp_path / "keys.enc"

    write_key_file(path, ENCRYPTION_KEY, keys)

    assert path.stat().st_mode & 0o777 == 0o600


def test_a_written_key_set_reads_back_able_to_sign_and_verify(
    tmp_path: Path, keys: SigningKeySet
) -> None:
    path = tmp_path / "keys.enc"
    rotated = rotate(keys)
    write_key_file(path, ENCRYPTION_KEY, rotated)

    reloaded = read_key_file(path, ENCRYPTION_KEY)

    assert reloaded.current.kid == rotated.current.kid
    assert reloaded.previous is not None
    minted = codec_for(reloaded).mint(
        tenant_id=uuid4(),
        user_id=uuid4(),
        client_id="syncr-cli",
        scopes=ALL_SCOPES,
        issued_at=NOW,
    )
    assert codec_for(reloaded).verify(minted.token, at=NOW) is not None


def test_another_deployments_encryption_key_cannot_read_the_file(
    tmp_path: Path, keys: SigningKeySet
) -> None:
    path = tmp_path / "keys.enc"
    write_key_file(path, ENCRYPTION_KEY, keys)

    with pytest.raises(RuntimeError, match="cannot be decrypted"):
        read_key_file(path, OTHER_ENCRYPTION_KEY)


def test_a_key_file_with_no_current_key_says_what_to_do_about_it(tmp_path: Path) -> None:
    # Only the rotation command writes this file, so the case is close to unreachable. A bare
    # `KeyError: 'current'` at boot is what it used to cost to be wrong about that.
    path = tmp_path / "keys.enc"
    path.write_bytes(Fernet(ENCRYPTION_KEY.encode("ascii")).encrypt(b'{"previous": null}'))

    with pytest.raises(RuntimeError, match="rotate-oauth-key"):
        read_key_file(path, ENCRYPTION_KEY)


def test_an_interrupted_write_leaves_the_previous_key_set_intact(
    tmp_path: Path, keys: SigningKeySet
) -> None:
    # The atomic-replace property. A key file that is half written is one the api cannot
    # parse, which is a boot failure rather than a degraded mode, so the temporary file is
    # what a failure damages.
    path = tmp_path / "keys.enc"
    write_key_file(path, ENCRYPTION_KEY, keys)
    original = path.read_bytes()

    with pytest.raises(ValueError, match="Fernet key"):
        write_key_file(path, "not-a-fernet-key", rotate(keys))

    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.tmp")) == [], "a temporary file survived a failed write"


def test_the_rotation_command_creates_the_file_and_then_rotates_it(tmp_path: Path) -> None:
    path = tmp_path / "keys.enc"

    first, retired = rotate_signing_keys(path, ENCRYPTION_KEY)
    second, now_retired = rotate_signing_keys(path, ENCRYPTION_KEY)

    assert retired is None
    assert now_retired == first
    assert second != first
    assert read_key_file(path, ENCRYPTION_KEY).current.kid == second


# --- Loading, and the refusal to run without keys --------------------------------------


def config_for(**overrides: object) -> OAuthConfig:
    env = EnvSettings(_env_file=None, **overrides)  # type: ignore[arg-type]
    return build_oauth_config(build_service_settings(service="test", env=env), is_dev=env.is_dev)


def test_development_with_no_key_file_gets_an_ephemeral_key_set() -> None:
    config = config_for(environment="development")

    loaded = load_signing_key_set(config)

    assert loaded.previous is None
    assert loaded.current.kid


def test_outside_development_a_missing_key_file_refuses_to_start() -> None:
    config = config_for(
        environment="production",
        session_signing_secret="a-real-session-signing-secret",  # pragma: allowlist secret
    )

    with pytest.raises(RuntimeError, match="OAUTH_KEYS_PATH"):
        load_signing_key_set(config)


@pytest.mark.parametrize(
    "unusable",
    ["typo-key", ENCRYPTION_KEY[:-4], "", f"{ENCRYPTION_KEY[:-1]}\u00e9"],
    ids=["not base64", "truncated", "empty", "non-ascii"],
)
def test_an_encryption_key_that_cannot_encrypt_is_refused_by_name(unusable: str) -> None:
    # Without this the value travels as far as the first read of the key file, where
    # `cryptography` reports "Fernet key must be 32 url-safe base64-encoded bytes" and names
    # neither the variable, nor the file, nor how to generate one.
    with pytest.raises(ValueError, match="OAUTH_KEY_ENCRYPTION_KEY is not a Fernet key") as refused:
        EnvSettings(
            _env_file=None,
            environment="production",
            session_signing_secret="a-real-session-signing-secret",  # pragma: allowlist secret
            oauth_keys_path="/var/lib/syncr/oauth-signing-keys.enc",
            oauth_key_encryption_key=unusable,
        )

    stated = str(refused.value)
    assert "/var/lib/syncr/oauth-signing-keys.enc" in stated
    assert "Fernet.generate_key" in stated


def test_an_unusable_encryption_key_is_ignored_where_nothing_is_encrypted_with_it() -> None:
    # Development with no key file encrypts nothing, and refusing the boot there would be a
    # guard on a value nothing reads.
    settings = EnvSettings(_env_file=None, environment="development", oauth_key_encryption_key="x")

    assert settings.oauth_keys_path == ""


def test_the_development_encryption_key_is_refused_where_a_key_file_exists() -> None:
    with pytest.raises(ValueError, match="OAUTH_KEY_ENCRYPTION_KEY"):
        EnvSettings(
            _env_file=None,
            environment="production",
            session_signing_secret="a-real-session-signing-secret",  # pragma: allowlist secret
            oauth_keys_path="/var/lib/syncr/oauth-signing-keys.enc",
            oauth_key_encryption_key=DEV_OAUTH_KEY_ENCRYPTION_KEY,
        )


def test_a_supplied_encryption_key_is_accepted_where_a_key_file_exists() -> None:
    # The control. Without it the assertions above would pass on a validator that refused
    # every value.
    settings = EnvSettings(
        _env_file=None,
        environment="production",
        session_signing_secret="a-real-session-signing-secret",  # pragma: allowlist secret
        oauth_keys_path="/var/lib/syncr/oauth-signing-keys.enc",
        oauth_key_encryption_key=ENCRYPTION_KEY,
    )

    assert settings.oauth_keys_path.endswith("oauth-signing-keys.enc")


# --- Audience binding ------------------------------------------------------------------


def test_a_token_carries_the_tenant_the_subject_and_the_scopes(keys: SigningKeySet) -> None:
    tenant_id, user_id = uuid4(), uuid4()
    codec = codec_for(keys)

    minted = codec.mint(
        tenant_id=tenant_id,
        user_id=user_id,
        client_id="syncr-cli",
        scopes=frozenset({Scope.PLAN_READ, Scope.PLAN_WRITE}),
        issued_at=NOW,
    )
    principal = codec.verify(minted.token, at=NOW)

    assert principal is not None
    assert principal.tenant_id == tenant_id
    assert principal.user_id == user_id
    assert principal.scopes == {Scope.PLAN_READ, Scope.PLAN_WRITE}
    assert minted.expires_in == int(ACCESS_TOKEN_LIFETIME.total_seconds())


def test_a_token_issued_for_another_audience_is_rejected(keys: SigningKeySet) -> None:
    # The binding that keeps P1 safe. A token minted for the MCP resource must not
    # authenticate anything at the syncr API, and the reverse is what the resource server
    # enforces with the same rule.
    minted_for_mcp = codec_for(keys, audience=OTHER_AUDIENCE).mint(
        tenant_id=uuid4(),
        user_id=uuid4(),
        client_id="syncr-cli",
        scopes=ALL_SCOPES,
        issued_at=NOW,
    )

    assert codec_for(keys).verify(minted_for_mcp.token, at=NOW) is None


def test_a_token_this_api_issued_is_rejected_on_any_other_audience(keys: SigningKeySet) -> None:
    minted_for_syncr = codec_for(keys).mint(
        tenant_id=uuid4(),
        user_id=uuid4(),
        client_id="syncr-cli",
        scopes=ALL_SCOPES,
        issued_at=NOW,
    )

    assert codec_for(keys, audience=OTHER_AUDIENCE).verify(minted_for_syncr.token, at=NOW) is None


def test_a_token_from_another_issuer_is_rejected(keys: SigningKeySet) -> None:
    minted_elsewhere = AccessTokenCodec(keys, issuer="https://impostor.example", audience=AUDIENCE)

    token = minted_elsewhere.mint(
        tenant_id=uuid4(),
        user_id=uuid4(),
        client_id="syncr-cli",
        scopes=ALL_SCOPES,
        issued_at=NOW,
    ).token

    assert codec_for(keys).verify(token, at=NOW) is None


def test_a_token_signed_by_a_key_this_server_never_held_is_rejected(keys: SigningKeySet) -> None:
    stranger = SigningKeySet(current=generate_signing_key("first"))

    token = (
        codec_for(stranger)
        .mint(
            tenant_id=uuid4(),
            user_id=uuid4(),
            client_id="syncr-cli",
            scopes=ALL_SCOPES,
            issued_at=NOW,
        )
        .token
    )

    # Same `kid`, different key: the signature check is what refuses it, not the lookup.
    assert codec_for(keys).verify(token, at=NOW) is None


def test_an_expired_token_is_rejected_against_the_injected_clock(keys: SigningKeySet) -> None:
    codec = codec_for(keys)
    minted = codec.mint(
        tenant_id=uuid4(),
        user_id=uuid4(),
        client_id="syncr-cli",
        scopes=ALL_SCOPES,
        issued_at=NOW,
    )

    assert codec.verify(minted.token, at=NOW + ACCESS_TOKEN_LIFETIME - timedelta(seconds=1))
    assert codec.verify(minted.token, at=NOW + ACCESS_TOKEN_LIFETIME) is None


def test_a_tampered_token_is_rejected(keys: SigningKeySet) -> None:
    codec = codec_for(keys)
    minted = codec.mint(
        tenant_id=uuid4(),
        user_id=uuid4(),
        client_id="syncr-cli",
        scopes=frozenset({Scope.PLAN_READ}),
        issued_at=NOW,
    )
    header, _original_payload, signature = minted.token.split(".")
    widened = (
        base64.urlsafe_b64encode(
            json.dumps(
                {**jwt.decode(minted.token, options={"verify_signature": False}), "scope": "admin"}
            ).encode()
        )
        .decode()
        .rstrip("=")
    )

    assert codec.verify(f"{header}.{widened}.{signature}", at=NOW) is None


@pytest.mark.parametrize(
    "presented",
    ["", "not-a-token", "a.b.c", "Bearer something"],
    ids=["empty", "opaque", "three parts", "with a scheme"],
)
def test_a_value_that_is_not_a_token_is_rejected(keys: SigningKeySet, presented: str) -> None:
    assert codec_for(keys).verify(presented, at=NOW) is None


# --- The discovery document ------------------------------------------------------------


def test_the_discovery_document_advertises_only_what_the_server_enforces() -> None:
    config = config_for(environment="development", public_base_url=ISSUER)

    document = build_metadata(config)

    assert document["issuer"] == ISSUER
    assert document["authorization_endpoint"] == f"{ISSUER}/oauth/authorize"
    assert document["token_endpoint"] == f"{ISSUER}/oauth/token"
    assert document["revocation_endpoint"] == f"{ISSUER}/oauth/revoke"
    assert document["jwks_uri"] == f"{ISSUER}/.well-known/jwks.json"
    assert document["code_challenge_methods_supported"] == ["S256"]
    assert "plain" not in json.dumps(document)
    assert document["scopes_supported"] == ["plan:read", "plan:write", "admin"]
    assert "registration_endpoint" not in document


def test_the_audience_is_the_versioned_api_under_the_pinned_issuer() -> None:
    config = config_for(environment="development", public_base_url=f"{ISSUER}/")

    assert config.issuer == ISSUER
    assert config.audience == f"{ISSUER}/api/v1"
