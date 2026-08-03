"""The Authorization Server: PKCE, tokens, signing keys, consent, and discovery.

syncr's API is both Authorization Server and Resource Server. There is no privileged hop
and therefore no internal application: the CLI is an OAuth client of the same API the
browser uses, holding an audience-bound scoped token, and when an MCP server arrives it
becomes another bearer client of the same surface.

Where each rule lives:

    config.py         the pinned URLs, the lifetimes, the one registered client
    errors.py         the protocol errors, as problem details with an OAuth type
    keys.py           the signing keys: generation, encryption at rest, rotation, JWKS
    access_tokens.py  the access token's claim set, signed and verified
    secrets.py        minting an opaque secret and the digest a row stores
    pkce.py           S256 verification, and the refusal of `plain`
    redirects.py      redirect-URI validation, loopback only for a public client
    authorization.py  the authorize request's rules and the consent screen's payload
    consent.py        that payload, rendered
    service.py        the two methods a signed-in browser calls to consent
    tokens.py         issuance, refresh with rotation, revocation, introspection
    repository.py     clients, codes, grants, refresh tokens
    cleanup.py        the expiry sweep the worker runs
    metadata.py       the RFC 8414 discovery document
"""
