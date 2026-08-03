# Rotate the OAuth signing key

The Authorization Server signs access tokens with a P-256 keypair and publishes the public
half at `/.well-known/jwks.json`. This runbook creates that key on a new deployment and
rotates it on schedule.

## When to run it

| Trigger | Action |
|---|---|
| A new deployment, before the api starts | Create the key file. The api refuses to start without one outside development |
| The rotation schedule, quarterly | Rotate |
| A suspected compromise of the key file or the host | Rotate immediately, then read "After an emergency rotation" below |
| `OAUTH_KEY_ENCRYPTION_KEY` is being changed | Rotate in the same operation: the file is encrypted under the old key and the api refuses a file it cannot decrypt |

## What rotation does

Two keys are held at all times. The current key signs; the previous key only verifies.
Rotation promotes the current key to previous and generates a new current key.

That is why a rotation is not an outage. An access token minted a minute before the
rotation names the old key in its header, the JWKS still publishes it, and it keeps
verifying until it expires fifteen minutes later. A key retired by a **second** rotation is
dropped, so two rotations inside one access-token lifetime would invalidate live tokens.
Leave at least an hour between rotations.

The private material is encrypted at rest with `OAUTH_KEY_ENCRYPTION_KEY`, which lives in
the host secret file and never beside the key file it protects.

## Prerequisites

- `OAUTH_KEYS_PATH` points at a path the rotating user can write and the api user can read.
- `OAUTH_KEY_ENCRYPTION_KEY` is set, and is not the development default.
- The api and worker containers mount the key file read-only.

Generate an encryption key once, at deployment time:

```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Steps

1. Confirm which file you are about to change:

   ```
   grep OAUTH_KEYS_PATH .env
   ```

2. Rotate:

   ```
   just rotate-oauth-key
   ```

   On the host, or inside the api container:

   ```
   docker compose run --rm api syncr-rotate-oauth-key
   ```

   It prints the new signing key's identifier and the one that is still trusted.

3. Restart the api so it reads the new key set. The worker does not sign or verify tokens
   and does not need restarting.

   ```
   docker compose up -d --force-recreate api
   ```

## How to verify it worked

1. The published key set carries two keys, and the first is the new one:

   ```
   curl -s https://<host>/.well-known/jwks.json | python -m json.tool
   ```

   Expect two entries, each with `"kty": "EC"`, `"alg": "ES256"`, `"use": "sig"`, and a
   distinct `kid`. No entry may contain a `d` member: that is the private scalar, and its
   presence means the public document is publishing the ability to mint tokens.

2. A client that held a token before the rotation still works. From a machine with the CLI
   signed in before step 2:

   ```
   syncr week show
   ```

   It must succeed without re-authorizing. If it fails with a 401, the previous key was not
   retained and every live token has been invalidated: rotate is not the fix, so read
   "If the api will not start" below.

3. A fresh sign-in works end to end:

   ```
   syncr auth login
   ```

## If the api will not start

| Message | Cause | Fix |
|---|---|---|
| `OAUTH_KEYS_PATH is empty` | No key file is configured, and this is not development | Set `OAUTH_KEYS_PATH` and run `just rotate-oauth-key` |
| `cannot be decrypted with OAUTH_KEY_ENCRYPTION_KEY` | The encryption key changed without the file being re-encrypted, or the file belongs to another deployment | Restore the matching encryption key, or delete the file and run `just rotate-oauth-key`. Deleting it signs out every CLI client |
| `OAUTH_KEY_ENCRYPTION_KEY is still the development default` | A deployment kept the value from `.env.example` | Generate a real key, re-encrypt by running `just rotate-oauth-key`, and restart |

Rotation writes through a temporary file and replaces the original only once the new
content is complete, so an interrupted rotation leaves the previous key set intact. If the
file is unreadable after a crash, the previous file is what is still there.

## After an emergency rotation

Rotation alone does not revoke anything. A stolen access token signed by the retired key
keeps verifying until it expires, and refresh tokens are unaffected by rotation entirely,
because they are opaque rows rather than signed claims.

To end access, revoke the grants as well:

1. Rotate, as above.
2. Have each client sign out, which revokes its refresh token family server-side:

   ```
   syncr auth logout
   ```

3. For a client that cannot be reached, delete its grants directly. This ends every family
   for the tenant:

   ```
   psql "$DATABASE_URL" -c "UPDATE oauth_grants SET revoked_at = now() WHERE revoked_at IS NULL;"
   psql "$DATABASE_URL" -c "UPDATE oauth_refresh_tokens SET revoked_at = now() WHERE revoked_at IS NULL;"
   ```

   Every client must then run `syncr auth login` again. Access tokens already issued remain
   valid for up to fifteen minutes, which is the documented cost of a signed credential the
   resource server verifies without a database read.

## What is not rotated here

- `SESSION_SIGNING_SECRET`. Rotating it signs every browser session out; see
  `docs/runbooks/bootstrap-first-user.md`.
- The Google OAuth client secret. Separate blast radius, separate runbook.
