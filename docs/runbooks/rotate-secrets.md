# Rotating a secret

## Trigger

Scheduled, or on suspicion. On suspicion is the case this runbook is written for: **rotate in the order
below and check what each rotation costs the user before starting**, because two of the eight cost
something and one of them signs everyone out.

The OAuth signing key has its own file, `rotate-oauth-signing-key.md`, because it is the one rotation
with a mechanism rather than a value: it promotes the current key to previous, publishes both, and lets
tokens signed before the rotation keep verifying. Everything else here is a value in the host secret
file.

## Where secrets live

`/opt/syncr/.env` on the host, mode 0600, **never in the repository**. Compose reads it for
interpolation and injects each value as an environment variable; the api and the worker read their own
from `env_file`. Nothing is baked into an image, and `just secret-scan` runs over the whole tree in CI
so a pasted one fails a gate rather than reaching a branch.

## The eight, and what rotating each one costs

| Secret | Cost of rotating | Who must act |
|---|---|---|
| `POSTGRES_PASSWORD` | A restart of everything that connects. **Change it in Postgres first**, or the stack cannot start | nobody |
| `SESSION_SIGNING_SECRET` | **Every browser session is invalidated.** Every session identifier is a keyed digest under it | the user signs in again |
| `OAUTH_KEY_ENCRYPTION_KEY` | The key file must be re-encrypted in the SAME operation. The api refuses to start against a file it cannot decrypt, and says so by name | nobody |
| The OAuth signing keys | Nothing: the JWKS publishes the previous key until tokens signed with it expire. `rotate-oauth-signing-key.md` | nobody |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Nothing, if the client id is unchanged | nobody |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | **Every stored refresh token becomes unreadable.** A token encrypted under the old key cannot be read back | the user reconnects Google |
| `CLOUDFLARE_TUNNEL_TOKEN` | The tunnel reconnects. **The hostname does not change** unless the tunnel itself is replaced | nobody |
| `RCLONE_CONFIG_OFFHOST_*` | Nothing, if the bucket is the same. New credentials to the same bucket are transparent | nobody |

And one that is not in the file at all:

| The backup recipient key | Cost |
|---|---|
| The gpg keypair the dumps are encrypted to | **Every earlier copy needs the earlier private key.** Rotating it does not re-encrypt what is in the bucket, so keep the old private half for as long as the retention window: 6 monthly copies means six months |

## Rotating a value

```
# 1. Generate. Each command is the one .env.example documents for that key.
python -c "import secrets; print('syncrp_' + secrets.token_urlsafe(48))"          # session secret
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Edit the host secret file. It is 0600 and root-owned; keep it that way.
vi /opt/syncr/.env

# 3. Restart what reads it. Compose re-reads the file on `up`.
docker compose $DEPLOY up -d api worker

# 4. Verify.
just await-ready
```

**Verification is not "the container started".** Each secret has something that only works if the value
is right:

| Secret | What proves it |
|---|---|
| `POSTGRES_PASSWORD` | `/readyz` answers 200, which needs a connection and a migration head |
| `SESSION_SIGNING_SECRET` | Sign in, then reload a screen: a session that survives a reload is a session the new secret signed |
| `OAUTH_KEY_ENCRYPTION_KEY` | The api starts at all. It refuses a file it cannot decrypt |
| `GOOGLE_TOKEN_ENCRYPTION_KEY` | Reconnect Google, then watch `syncr_write_target_token_age_seconds` return to 0 |
| `CLOUDFLARE_TUNNEL_TOKEN` | The tunnel hostname answers `/healthz` from outside |
| `RCLONE_CONFIG_OFFHOST_*` | `just backup-now`, then `just restore-drill`. A credential that can write and not read is the worst case here |

## Rotating the backup recipient key

The one rotation with a retention window, and the one that must be **re-drilled**:

```
# 1. On a machine that is NOT the VPS:
gpg --quick-generate-key 'syncr backups 2027 <you@example.com>' default default never
gpg --armor --export 'syncr backups 2027' > backup-recipient.asc

# 2. Keep the OLD private half. Every copy already in the bucket needs it.
# 3. Copy only the public half to the host:
scp backup-recipient.asc root@host:/opt/syncr/deployments/secrets/

# 4. Take a backup with the new key, and drill it:
just backup-now
SYNCR_BACKUP_PRIVATE_KEY=<new private half> just restore-drill
```

**Re-execute the drill after any change to the backup path.** That is this deployment's own rule, and a
key rotation is a change to the backup path: an encryption whose private half has never been used is a
belief in the same way an untested backup is.

## What not to do

- **Do not rotate two secrets in one restart** when one of them costs the user something. If the stack
  then fails to start, you have two candidates and one of them signed everybody out.
- **Do not put a secret in the repository "temporarily".** The pre-commit scan will catch a
  high-entropy string, and `git log` keeps what it does not catch.
- **Do not rotate `GOOGLE_TOKEN_ENCRYPTION_KEY` while the write target is in use** without telling the
  user: the projection stops until they reconnect, and the banner says so but the calendar goes stale
  from that moment.
- Do not delete the old backup recipient private key until the retention window has passed.

## On suspicion of compromise

Order matters, because the first two close the door and the rest change the locks:

1. `docker compose $DEPLOY stop cloudflared`: the only ingress. Nothing else needs to be reachable.
2. `SESSION_SIGNING_SECRET`: every live session is invalidated by the change itself.
3. `POSTGRES_PASSWORD`, then the two encryption keys, then the Google client secret.
4. The tunnel token, and consider replacing the tunnel rather than its token.
5. The backup recipient key, and keep the old private half.
6. A backup and a drill, in that order, so what you recovered to is itself recoverable.

## Not verified

- **No secret has ever been rotated on a deployment**, because no deployment exists. The commands are
  the ones `.env.example` documents and the ones the recipes run; the sequence has not been executed.
- **`just rotate-oauth-key` has been run**, by ticket 6, on a development machine. The others have not.
