/* Fixture: a second hop, so the walk is proved to go deeper than one extra step.
 *
 * primitives -> lib/deep -> lib/handy -> api/client. A walk that looked only one hop past the first
 * would call this clean. */

export { apiFetch } from "./handy.ts";
