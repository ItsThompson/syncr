"""The signing keys: generated, encrypted at rest, rotated, and published as a JWKS.

An access token is a signed claim set the resource server verifies without a database
read, which is what makes a bearer credential cheap. Signing is asymmetric (ES256, a
P-256 keypair) so the public half can be published: today the Resource Server is this
same process and a shared secret would do, but P1's MCP server verifies the same tokens,
and a symmetric key cannot be published to a verifier without handing it the power to
mint.

**Two keys are held, not one.** The current key signs; the previous key only verifies.
Rotation promotes current to previous and generates a new current, and the JWKS carries
both, so tokens signed a minute before a rotation keep verifying until they expire. With
one key, rotation would invalidate every live token at once, which is an outage rather
than a maintenance operation.

**The private material is encrypted at rest with a key from the environment.** The file
holds a Fernet-encrypted JSON document; the encryption key is ``OAUTH_KEY_ENCRYPTION_KEY``
and never touches the disk beside it. So a filesystem backup, a snapshot, or a stolen
volume yields ciphertext.

**The application never writes this file.** Startup reads it, and only
``syncr-rotate-oauth-key`` writes it, so a process that boots cannot silently mint a new
key set and orphan the one clients are verifying against. With no file configured,
development generates an ephemeral key set in memory and every other environment refuses
to start, because a JWKS whose keys change on every restart invalidates every live token
on every deploy.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from syncr_common.logging import get_logger

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ec import (
        EllipticCurvePrivateKey,
        EllipticCurvePublicKey,
    )

    from syncr_api.oauth.config import OAuthConfig

# ES256 is a P-256 keypair with SHA-256, which is the most widely implemented asymmetric
# JWS algorithm after RS256 and produces a 64-byte signature against RSA-2048's 256. A
# token is carried in an `Authorization` header on every request, so its size is a running
# cost rather than a one-off.
SIGNING_ALGORITHM = "ES256"
JWK_USE_SIGNATURE = "sig"

# The two slots. A key is addressed by `kid`, which is what lets a verifier pick the right
# one out of the JWKS without trying both.
CURRENT_SLOT = "current"
PREVIOUS_SLOT = "previous"

# Owner-read-only, because the file holds the private half even though it is encrypted.
KEY_FILE_MODE = 0o600

_log = get_logger("syncr.oauth")


@dataclass(frozen=True, slots=True)
class SigningKey:
    """One keypair and the ``kid`` a token's header names it by."""

    kid: str
    private_key: EllipticCurvePrivateKey

    @property
    def public_key(self) -> EllipticCurvePublicKey:
        return self.private_key.public_key()

    def as_public_jwk(self) -> dict[str, Any]:
        """This key's public half as a JWK, with the members a verifier selects on."""
        # PyJWT renders the curve point; `kid`, `use`, and `alg` are what make the key
        # selectable and are not part of the point, so they are added rather than derived.
        exported: dict[str, Any] = ECAlgorithm.to_jwk(self.public_key, as_dict=True)
        return {**exported, "kid": self.kid, "use": JWK_USE_SIGNATURE, "alg": SIGNING_ALGORITHM}


@dataclass(frozen=True, slots=True)
class SigningKeySet:
    """The key that signs, and the retired key that still verifies."""

    current: SigningKey
    previous: SigningKey | None = None

    def verifying_keys(self) -> tuple[SigningKey, ...]:
        """Every key a presented token may have been signed with."""
        return (self.current,) if self.previous is None else (self.current, self.previous)

    def find(self, kid: str | None) -> SigningKey | None:
        """The key a token's ``kid`` names, or ``None`` when this server never held it."""
        return next((key for key in self.verifying_keys() if key.kid == kid), None)

    def jwks(self) -> dict[str, Any]:
        """The published JWKS document. Public material only, current key first."""
        return {"keys": [key.as_public_jwk() for key in self.verifying_keys()]}


def generate_signing_key(kid: str) -> SigningKey:
    """A fresh P-256 keypair under ``kid``."""
    return SigningKey(kid=kid, private_key=ec.generate_private_key(ec.SECP256R1()))


def load_signing_key_set(config: OAuthConfig) -> SigningKeySet:
    """The key set this process signs and verifies with.

    Reads the configured encrypted file. With no path configured, development generates an
    ephemeral set and says so at warning level; every other environment raises, because
    ephemeral keys mean every restart invalidates every token it ever issued.
    """
    if config.keys_path:
        return read_key_file(Path(config.keys_path), config.key_encryption_key)
    if not config.is_dev:
        message = (
            "OAUTH_KEYS_PATH is empty, so the OAuth signing keys would be regenerated on "
            "every restart and every live access token would stop verifying. Create the "
            "file with `just rotate-oauth-key` and point OAUTH_KEYS_PATH at it; see "
            "docs/runbooks/rotate-oauth-signing-key.md."
        )
        raise RuntimeError(message)
    _log.warning("oauth.keys.ephemeral", reason="no_keys_path_configured")
    return SigningKeySet(current=generate_signing_key(_new_kid()))


def read_key_file(path: Path, encryption_key: str) -> SigningKeySet:
    """Decrypt and parse the key file at ``path``.

    Every failure is raised rather than recovered from. A key set that cannot be read is
    not a degraded mode: the server would issue tokens under a key nobody can verify, so
    it must not start.
    """
    try:
        plaintext = Fernet(encryption_key.encode("ascii")).decrypt(path.read_bytes())
    except InvalidToken as invalid:
        message = (
            f"the OAuth signing keys at {path} cannot be decrypted with "
            "OAUTH_KEY_ENCRYPTION_KEY. Either the key was rotated without re-encrypting "
            "the file, or the file belongs to another deployment."
        )
        raise RuntimeError(message) from invalid
    document = json.loads(plaintext)
    return SigningKeySet(
        current=_key_from_document(document[CURRENT_SLOT]),
        previous=(
            _key_from_document(document[PREVIOUS_SLOT])
            if document.get(PREVIOUS_SLOT) is not None
            else None
        ),
    )


def write_key_file(path: Path, encryption_key: str, keys: SigningKeySet) -> None:
    """Encrypt ``keys`` and replace ``path`` atomically, owner-readable only.

    Written to a sibling temporary file, flushed to disk, and renamed, so a crash or a
    full filesystem cannot leave a half-written key set: the old file survives intact
    until the new one is complete. The mode is set before any content is written, so the
    private material is never briefly world-readable.
    """
    document = {
        CURRENT_SLOT: _document_from_key(keys.current),
        PREVIOUS_SLOT: _document_from_key(keys.previous) if keys.previous else None,
    }
    ciphertext = Fernet(encryption_key.encode("ascii")).encrypt(
        json.dumps(document).encode("utf-8")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, KEY_FILE_MODE)
        with os.fdopen(handle, "wb") as opened:
            opened.write(ciphertext)
            opened.flush()
            os.fsync(opened.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def rotate(keys: SigningKeySet | None, *, kid: str | None = None) -> SigningKeySet:
    """The key set after a rotation: a new current key, the old current retired.

    The key that was previous is dropped, not kept as a third. It signed nothing more
    recently than two rotations ago, so every token it signed has expired by any
    rotation schedule wider than the access-token lifetime, and keeping it would publish a
    verifiable key for no live token.
    """
    fresh = generate_signing_key(kid or _new_kid())
    return SigningKeySet(current=fresh, previous=keys.current if keys else None)


def _new_kid() -> str:
    """A key identifier. Random rather than sequential, so it names one key forever.

    A counter would be reused by a deployment restored from a backup taken before a
    rotation, and two different keys under one ``kid`` is a verification failure that
    reads as a bad signature.
    """
    return uuid4().hex


def _key_from_document(document: dict[str, str]) -> SigningKey:
    return SigningKey(
        kid=document["kid"],
        private_key=cast(
            "EllipticCurvePrivateKey", ECAlgorithm.from_jwk(json.dumps(document["jwk"]))
        ),
    )


def _document_from_key(key: SigningKey) -> dict[str, object]:
    return {"kid": key.kid, "jwk": json.loads(ECAlgorithm.to_jwk(key.private_key))}
