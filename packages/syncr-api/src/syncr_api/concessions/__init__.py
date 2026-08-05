"""The concession package: requesting a tradeoff, and the concessions an approval left behind.

| Module | Holds |
|---|---|
| ``config.py`` | the two collection paths under one week, and the wire field names |
| ``declarations.py`` | what a caller asks for: a kind and a target, and no figures |
| ``schemas.py`` | the request body and the concession the panel lists |
| ``service.py`` | the three acts: request, read, revoke |
| ``api.py`` | the three routes, each calling one service method |
| ``injection.py`` | the one place its collaborators are composed, scoped to a tenant |
| ``wiring.py`` | the router the app factory asks for |

**Requesting persists nothing.** The enumeration lives with the assembler, in
:mod:`syncr_api.plans.tradeoffs`, because it reads a resolved week; what lives here is the request
path, which turns one offered tradeoff into a candidate riding on an operation, and the two reads
that follow an approval.
"""
