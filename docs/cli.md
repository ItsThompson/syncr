# syncr CLI Reference

This page is the user reference for the `syncr` command-line client: every command with its flags, the exit codes a caller branches on, where configuration lives and how it is resolved, and the sign-in flow end to end. The CLI exists for the user at a terminal and for the user's AI agent, so it carries agent-facing obligations: `--json` on every command, stable exit codes, idempotent mutations, complete self-describing `--help`, and no interactive prompts: nothing in the client reads stdin, ever. It is an OAuth client of the same API the browser uses; see [prd.md](prd.md) for the product's place for it and [architecture.md](architecture.md) for how it sits among the repository members.

Each section names the source file that owns its facts. This page states stable concepts and vocabulary; the help text (`syncr <noun> <verb> --help`) remains the complete per-command truth and prints the exit-code table itself.

## Conventions

Commands are noun then verb, following `gh`: `syncr auth login`, `syncr week show`.

Every shared flag is accepted on either side of the verb, so `syncr --json week show` and `syncr week show --json` are the same invocation. A person types one and an agent generates the other.

A parse failure or a bad setting exits 2 and answers in the configured output format like any other failure: an agent parsing `--json` receives the same error wrapper whatever went wrong.

## Shared flags

Every command accepts these, defined once in `cli/src/syncr_cli/parser.py`:

| Flag | Meaning |
|---|---|
| `--api-url URL` | The API to talk to, without a trailing slash. |
| `--week ISO_WEEK` | The week to act on, as `2026-W07`. Defaults to this machine's current ISO week. |
| `--output human\|json` | How to write the result. Default: `human` on a terminal, `json` otherwise. |
| `--json` | Shorthand for `--output json`. |
| `--poll-interval MS` | How often to poll a long-running operation while waiting. |
| `--timeout S` | How long to wait on an operation before exiting 10. |
| `--idempotency-key KEY` | The key a mutation carries. Derived from the command and its arguments when absent. |

## Configuration

Canonical source: `cli/src/syncr_cli/config_file.py` and `cli/src/syncr_cli/settings.py`.

The configuration file lives at `$XDG_CONFIG_HOME/syncr/config.toml`, which is `~/.config/syncr/config.toml` when the variable is unset. Having no file is the ordinary case; every setting has a built-in default.

Five keys are read, and no others:

| Key | Kind | Built-in default |
|---|---|---|
| `api_url` | Text, an http or https URL | `http://localhost:8000`, the development host; a deployment states its own |
| `poll_interval_ms` | Whole number of milliseconds, minimum 1 | 500 |
| `timeout_s` | Whole number of seconds, minimum 1 | 60 |
| `week` | ISO week, as `2026-W07` | The machine's current ISO week |
| `output` | `human` or `json` | `human` on a terminal, `json` otherwise |

Precedence runs, highest first: **the command flag, then the `SYNCR_` environment variable, then the configuration file, then the built-in default**: `SYNCR_API_URL`, `SYNCR_POLL_INTERVAL_MS`, `SYNCR_TIMEOUT_S`, `SYNCR_WEEK`, `SYNCR_OUTPUT`. One resolver answers for all five settings, so no command reads them in a different order from another. An empty environment variable counts as unstated rather than as an empty value.

The file is refused, with exit 2 and a message that says what to do, when it is not readable as TOML, or when it names a key outside the five above. A misspelled setting that was silently ignored would be a setting the user believes they set.

Credentials never appear here. The refresh token lives in the OS keychain, with a file fallback described under [sign-in](#signing-in).

## Exit codes

Canonical source: `cli/src/syncr_cli/exit_codes.py`. The set is closed, each number means one thing, and this same table is printed by `--help` on the root parser and on every command. An agent branches on the number before reading any output.

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | generic failure |
| 2 | usage error: bad flag, missing argument, malformed value |
| 3 | not authenticated, or the refresh token is invalid |
| 4 | authenticated but insufficient scope |
| 5 | not found |
| 6 | conflict: an off-plan overlap, a second write target, a cleared proposal |
| 7 | validation failure: a minimum chunk above an estimate |
| 8 | INFEASIBLE. The command succeeded and the week cannot hold its commitments |
| 9 | operation superseded: a later edit displaced it, and it names its successor |
| 10 | operation timed out while waiting. Distinct from a failure |
| 11 | the API is unavailable |

Three of these are not failures. An infeasible week (8) is the product working correctly, a superseded solve (9) is the expected result of editing quickly, and a timed-out wait (10) says nothing about the work it was waiting on; it carries the operation identifier so the wait can be resumed. Collapsing any of them into 1 would make an agent treat a normal outcome as an error.

## Command catalog

Sixteen verbs under seven nouns. Canonical source: `cli/src/syncr_cli/commands/`. Every command also takes the [shared flags](#shared-flags); only command-specific flags are repeated below.

### auth: authorize this machine, and report what it holds

Source: `cli/src/syncr_cli/commands/auth.py`. See [signing-in](#signing-in) for the flow behind these.

| Command | Flags | What it does |
|---|---|---|
| `syncr auth login` | none | Authorize through a browser with PKCE. Requests `plan:read` and `plan:write`, never `admin`. Stores the refresh token. |
| `syncr auth logout` | none | Revoke this machine's refresh token server-side, then remove it locally. If revocation fails, the local token is kept so it can be tried again. |
| `syncr auth status` | none | The principal this machine is authenticated as, the granted scopes, and which store holds the token. |

### task: capture, list, and complete tasks

Source: `cli/src/syncr_cli/commands/task.py`. Both mutations answer with the task as the API now holds it, and both carry a derived idempotency key, so retrying the same command does not capture twice.

| Command | Flags | What it does |
|---|---|---|
| `syncr task add TITLE` | `--area AREA_ID` (required), `--estimate MINUTES`, `--deadline INSTANT`, `--priority PRIORITY`, `--min-chunk MINUTES`, `--atomic` | Capture one task. Only what you state is sent: every other field keeps the API's documented default. `--atomic` places the task as one block of the whole estimate or not at all. |
| `syncr task list` | `--area AREA_ID`, `--status open\|completed\|dropped`, `--at-risk` | List tasks with filters. Every status unless one is named. `--at-risk` asks for the rows the current verdict reports a deadline shortfall for. |
| `syncr task done TASK_ID` | none | Complete a task. It leaves solver eligibility and keeps its recorded time. |

### backlog: read the backlog

Source: `cli/src/syncr_cli/commands/backlog.py`.

| Command | Flags | What it does |
|---|---|---|
| `syncr backlog list` | `--area AREA_ID`, `--status …` (defaults to `open`), `--at-risk` | The outstanding work, plus the header count of tasks the current verdict marks at risk. The at-risk figure is read from the server, never computed locally. |

### week: read a week

Source: `cli/src/syncr_cli/commands/week.py`.

| Command | Flags | What it does |
|---|---|---|
| `syncr week show` | none | The week as a plan: readings, the verdict and its provenance, day rows. Exits 8 when the week cannot hold its commitments. |

### plan: read, solve, and approve a plan

Source: `cli/src/syncr_cli/commands/plan.py`. Solving is asynchronous; there is no streaming client, so `plan solve --wait` polls the operation, capped by `--timeout` and stepping by `--poll-interval`.

| Command | Flags | What it does |
|---|---|---|
| `syncr plan show` | `--date DATE` | The live plan for a week, or one date's ledger with `--date`. Exits 8 when the week cannot hold its commitments. |
| `syncr plan solve` | `--wait`, `--immediate` | Request a solve and print the operation, exiting 0 immediately. With `--wait`, poll to a terminal status and exit by it: 0 succeeded, 1 failed with the server's cause, 9 superseded (naming the displacing operation), 10 timed out carrying the resumable operation. `--immediate` bypasses the debounce window. |
| `syncr plan approve` | none | Approve the pending proposal, making it the plan of record. Approval always sends an explicit idempotency key because there is no unapprove. Exits 6 when the slot has been cleared. |

### block: record what happened to a block, or move one

Source: `cli/src/syncr_cli/commands/block.py`. Recording an outcome does not confirm the day; `day confirm` settles it. All four name the week through `--week` (default: the current ISO week).

| Command | Flags | What it does |
|---|---|---|
| `syncr block done BLOCK_ID` | none | Record a completed outcome. |
| `syncr block skip BLOCK_ID` | none | Record a skipped outcome. The day stays unconfirmed. |
| `syncr block partial BLOCK_ID` | `--minutes MINUTES` (required) | Record a partial outcome with the minutes it really took. |
| `syncr block move BLOCK_ID` | `--to INSTANT` (required) | Move a block to a new start instant, creating a pin; length unchanged. Reports the resulting verdict, exiting 8 if the move broke the week, with the follow-up solve named beside it. |

### day: answer for a day

Source: `cli/src/syncr_cli/commands/day.py`.

| Command | Flags | What it does |
|---|---|---|
| `syncr day confirm [DATE]` | none | Convert presumed to recorded for one date, defaulting to this machine's today. Unmentioned blocks are recorded as presumed complete, and the settled ledger is read back. |

## Idempotent mutations

Every mutation carries an `Idempotency-Key`. By default the key is derived from the command and its arguments, so retrying an identical invocation lands the same row instead of a second one. Two genuinely distinct identical captures need `--idempotency-key` to say so. Canonical source: `cli/src/syncr_cli/idempotency.py`.

## Output formats

Every command renders twice-capable results in exactly one of two formats: `human` for a person at a terminal, `json` for everything else. Because the default format is chosen by whether stdout is a terminal, piping or capturing output produces machine-readable JSON with no flag. Errors answer in the same wrapper as successes, including usage errors, so an agent parsing `--json` gets a parseable document whatever happened. Canonical source: `cli/src/syncr_cli/results.py` and `cli/src/syncr_cli/main.py`.

## Signing in

`syncr auth login` runs an OAuth authorization code flow with PKCE, end to end:

1. **Discover the server.** The client reads the deployment's OAuth metadata at `/.well-known/oauth-authorization-server`. Endpoint URLs are discovered, not compiled in, and the deployment must advertise the `S256` PKCE method; the client will not fall back to a weaker mode.
2. **Prepare the exchange.** It generates a one-time code verifier and derives an `S256` code challenge, plus a random `state` nonce.
3. **Listen locally.** A listener starts on `127.0.0.1` on an ephemeral port, so two concurrent logins cannot collide and only this machine can deliver the code.
4. **Open the consent screen.** A browser opens at the authorization endpoint. On a headless machine the URL is printed to paste instead; the client opens the browser but never drives it, because approving scopes is the user's act.
5. **Approve named scopes.** The consent screen names what is requested: `plan:read` and `plan:write`. `admin` is never asked for, so a stolen CLI token cannot reach calendar-source setup or template editing. A scope refusal arrives on the redirect as an error and fails immediately.
6. **Receive the code.** The single-use authorization code comes back to the loopback listener, with the `state` checked against what was sent.
7. **Exchange and store.** The code is exchanged at the token endpoint. The refresh token is stored in the OS keychain, keyed by API URL so one machine can hold credentials for two deployments. Where no keychain works, the token falls back to `$XDG_CONFIG_HOME/syncr/credentials.json` (which is `~/.config/syncr/credentials.json` when the variable is unset, the same base as the configuration file), created atomically at mode `0600`, and the fallback is announced, never silent. No environment variable or flag can carry a credential.
8. **Finish.** The whole flow allows five minutes for a human to sign in; a forgotten terminal does not hold a listener open all day.

`syncr auth status` then reports the principal, the granted scopes, and which store answered. `syncr auth logout` revokes the grant server-side before removing anything locally, so a user who was told the grant is dead is never left holding a live credential. Canonical source: `cli/src/syncr_cli/auth/`.
