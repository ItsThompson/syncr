"""Encryption, with the key that can DECRYPT held off the host.

The requirement is "encrypted at rest in the bucket, with a key held outside the VPS", and a
symmetric passphrase in the host's secret file does not meet it: an attacker who reaches the host to
read the database also reads the passphrase, so the copies protect nothing they did not already
have.

So the host holds a PUBLIC key and nothing else. gpg's hybrid encryption generates a session key per
file, encrypts the file with it, and wraps the session key to the recipient. Decrypting needs the
private key, which lives off the host and is brought to the drill by a person. That is also why the
restore drill is the only thing that proves the arrangement works: an encryption whose private half
has never been used is a belief in the same way an untested backup is.

``--recipient-file`` takes the armoured public key directly, so nothing imports into a keyring
inside an image whose filesystem is discarded on the next deploy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from ops.process import Run

# gpg's own name for "the file may be armoured or binary, read it and use it as a recipient".
_RECIPIENT = "--recipient-file"


class EncryptionRefused(Exception):
    """There is no key to encrypt to, so the upload would put plain user data in a bucket."""


def encrypt(source: Path, *, into: Path, public_key: Path, run: Run, gpg: str = "gpg") -> Path:
    """Encrypt one file to the recipient in ``public_key``, returning the file written.

    Refuses when the key is absent rather than falling back to an unencrypted upload. Every block
    title in this dump is sensitive: a plain copy in a bucket is the disclosure the whole storage
    decision exists to prevent.
    """
    if not public_key.is_file():
        raise EncryptionRefused(
            f"{public_key} does not exist, so there is no recipient to encrypt to. The dump holds "
            "every block title and every anchor location; it is not uploaded in the clear."
        )
    run(
        [
            gpg,
            "--batch",
            "--yes",
            # The recipient is a file this deployment put there, so there is no web of trust to
            # consult and no interactive prompt to hang on.
            "--trust-model",
            "always",
            _RECIPIENT,
            str(public_key),
            "--encrypt",
            "--output",
            str(into),
            str(source),
        ]
    )
    return into


def decrypt(source: Path, *, into: Path, home: Path, run: Run, gpg: str = "gpg") -> Path:
    """Decrypt one file with the private key already imported into ``home``.

    ``home`` is a GNUPGHOME the drill creates, imports the off-host private key into, and destroys.
    The key is never written into an image and never lands in the deployment's own gpg home.
    """
    run(
        [
            gpg,
            "--batch",
            "--yes",
            "--homedir",
            str(home),
            "--decrypt",
            "--output",
            str(into),
            str(source),
        ]
    )
    return into


def import_private_key(key: Path, *, home: Path, run: Run, gpg: str = "gpg") -> None:
    """Import the off-host private key into a throwaway gpg home."""
    home.mkdir(parents=True, exist_ok=True)
    home.chmod(0o700)
    run([gpg, "--batch", "--yes", "--homedir", str(home), "--import", str(key)])
