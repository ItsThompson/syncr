"""The one Google account this tenant connected, and the credential that keeps it connected.

A calendar source is a calendar. This package is the ACCOUNT: one OAuth grant per tenant,
whose refresh token is the standing authority behind every Google read and the one destructive
write. The two are separate because they fail separately and are repaired separately. A feed
that stops answering is one source in an error state; a refresh token that dies takes every
Google source and the projection with it, and the repair is a browser consent rather than a
retry.

Three things live here and nowhere else.

**The refresh token, encrypted at rest.** It never leaves this package in plaintext and never
reaches a log line. What the calendar package receives is an access token with a lifetime of
minutes, from :class:`~syncr_api.google_account.tokens.GoogleAccessTokens`.

**Why writes are failing, and since when.** A refresh failure is recorded on the credential
with the instant it started, because the notice the product raises has to state how long the
plan has not been reaching the phone. That is the most dangerous silent failure in syncr: the
reads keep working, so nothing else looks wrong.

**The consent surface.** The scopes are named in plain language before the user is sent to
Google, along with which calendars syncr will read, because Google's own screen names neither.
"""
