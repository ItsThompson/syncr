"""Encrypting the refresh token at rest, and refusing to pretend when the key is wrong.

One value is encrypted: the Google refresh token, which is the standing authority to read every
calendar in the account and to overwrite the one syncr owns. Fernet is symmetric authenticated
encryption, so a stored token cannot be read or altered without the key from the environment,
and a row copied out of a database dump is inert without it.

**A ciphertext that will not decrypt is a dead credential, not an error to swallow.** The key
rotated, the row came from another deployment, or the column was edited: in every case the
grant is unusable and the answer is the same as an expired refresh token, a reconnect. So
:func:`decrypt_refresh_token` reports that rather than raising something a caller has to know
to catch, and the reconnect notice is what the user sees.

Nothing here logs, and nothing here renders a value into a message. A plaintext token has
exactly two destinations: the token endpoint, and the encryptor.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken

from syncr_api.core.settings import DEV_GOOGLE_TOKEN_ENCRYPTION_KEY
from syncr_api.google_account.config import REFRESH_TOKEN_MAX_LENGTH


def is_published_key(key: str) -> bool:
    """Whether this key is the development default, which this repository publishes.

    A refresh token encrypted under a key any reader of the repository holds is a refresh token in
    the clear, and a refresh token is standing authority to read every calendar in the account and
    to overwrite the one syncr owns.

    Asked where a token is about to be encrypted rather than where settings are loaded. Settings are
    constructed by every process, every test, and ``alembic``, against whatever the root env file
    holds; refusing there would fail a boot that stores nothing, which is what it did.
    """
    return key == DEV_GOOGLE_TOKEN_ENCRYPTION_KEY


class RefreshTokenTooLong(ValueError):
    """The provider issued a refresh token wider than the column that holds it.

    Its own class because the answer differs from every other failure on the connect path: a
    token syncr cannot store is not a token the user can fix by consenting again, and it must
    be refused before a write that would roll back the transaction it is in.
    """


@dataclass(frozen=True, slots=True)
class TokenCipher:
    """Encrypts and decrypts one deployment's stored refresh tokens.

    The key is passed in rather than read from the environment here, so the settings layer
    stays the only reader of the environment and a test supplies its own key.
    """

    key: str

    def encrypt(self, refresh_token: str) -> str:
        """The stored form of ``refresh_token``.

        Bounded before encryption rather than after, because the ciphertext's length is a
        function of the plaintext's and the message that names the provider's value is worth
        more than one that names a base64 length.
        """
        if len(refresh_token) > REFRESH_TOKEN_MAX_LENGTH:
            message = (
                f"Google issued a refresh token of {len(refresh_token)} characters, and syncr "
                f"stores up to {REFRESH_TOKEN_MAX_LENGTH}."
            )
            raise RefreshTokenTooLong(message)
        return self._fernet().encrypt(refresh_token.encode("utf-8")).decode("ascii")

    def decrypt(self, stored: str) -> str | None:
        """The refresh token ``stored`` holds, or ``None`` when this key cannot read it."""
        try:
            return self._fernet().decrypt(stored.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError):
            return None

    def _fernet(self) -> Fernet:
        """The cipher for this key.

        Built per call rather than held, because ``Fernet`` is cheap to construct and holding
        one would keep the key material alive on an instance that outlives a request.
        """
        return Fernet(self.key.encode("ascii"))
