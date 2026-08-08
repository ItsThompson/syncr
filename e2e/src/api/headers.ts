/* The header and cookie names the api reads, in one place.
 *
 * Each is a wire constant with exactly one spelling on the Python side, named there in
 * `accounts/config.py`, `idempotency/config.py` and `core/session_mode.py`. They are restated here
 * rather than derived, because nothing generates them into the OpenAPI document: `Idempotency-Key`
 * and `X-Syncr-Session-Mode` are request headers a route reads, not schema fields.
 *
 * A misspelling here fails loudly rather than quietly. An unknown cookie name is no session, so
 * every request is a 401; an unknown idempotency header makes the replay case duplicate, which is
 * the assertion that reads it; and an unknown session-mode header makes the session-attributed
 * verdict scenario fail on its `surface`.
 */

export const SESSION_COOKIE = "syncr_session";
export const IDEMPOTENCY_KEY_HEADER = "Idempotency-Key";
export const SESSION_MODE_HEADER = "X-Syncr-Session-Mode";
export const ORIGIN_HEADER = "Origin";
