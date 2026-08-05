"""The OAuth client half of the flow, and where the refresh token is kept.

Every module in this package appears in the table below.

| Module | Holds |
|---|---|
| ``pkce.py`` | The verifier, the S256 challenge, and why the method is always stated |
| ``discovery.py`` | RFC 8414 metadata, the client id, and the scopes this CLI requests |
| ``loopback.py`` | The one-shot listener on an ephemeral loopback port |
| ``flow.py`` | The authorization code flow, end to end |
| ``tokens.py`` | The token endpoint: exchange, refresh, and revoke |
| ``session.py`` | The access token, in memory, for one invocation |
| ``storage.py`` | The keychain, the 0600 file fallback, and the notice that says which |
| ``claims.py`` | The claims an access token carries, read for display only |
"""
