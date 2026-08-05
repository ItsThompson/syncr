"""The syncr CLI: an OAuth client of the same API the browser uses.

The CLI is a **deliberate subset, not parity**. It exists for the user at a terminal and for the
user's AI agent, and because an agent is a first-class client it is an API surface with the
matching obligations: a documented wrapper on every ``--json`` response, stable exit codes per
failure class, no interactive prompt, an idempotency key on every mutation, and a ``--help``
complete enough to work from without external documentation.

## The AI boundary

**The language model is never load-bearing for correctness.** The agent is a driver, not a
planner: it translates intent into commands and reads results back, and it never computes a
schedule. Placement is deterministic code behind the API, so identical inputs produce identical
plans and no model sits in the placement loop. That is what lets this product have an AI story
with none of the correctness risk one usually brings.

## What this package holds

Every module in this package appears in the table below.

| Module | Holds |
|---|---|
| ``main.py`` | The entrypoint: parse, dispatch, render once, exit |
| ``parser.py`` | The command line: nouns, verbs, shared flags, and the help each carries |
| ``runtime.py`` | One invocation's settings, streams, and lazily built collaborators |
| ``settings.py`` | The five settings and the four places each may come from |
| ``config_file.py`` | ``~/.config/syncr/config.toml``, located and read |
| ``results.py`` | ``CliResult``: the one shape every command answers with |
| ``exit_codes.py`` | The twelve codes, and the table ``--help`` prints |
| ``problems.py`` | RFC 9457 problem details, read and minted, and the code each maps to |
| ``errors.py`` | The failures a command raises, each carrying its problem |
| ``http.py`` | The one place this package speaks HTTP |
| ``api_client.py`` | The product's routes, as this client calls them |
| ``operations.py`` | Waiting on an operation: poll, back off, and end with a code |
| ``idempotency.py`` | The key a mutation carries, derived deterministically |
| ``notices.py`` | What the process says on stderr beyond its result |

Four subpackages: ``auth`` holds the OAuth flow and the credential store, ``wire`` reads the
payloads the api sends, ``rendering`` writes them for a person or for an agent, and ``commands``
holds one module per noun.
"""
