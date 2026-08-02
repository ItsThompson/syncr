/* Fixture: the laundering re-export. One line in `lib/`, which EVERY zone may read, and nothing
 * constrained what `lib/` itself imports.
 *
 * A primitive importing `../../lib/handy` looks entirely innocent, and the first hop is genuinely
 * permitted. The violation is one hop further on, which is why the walk is transitive. */

export { apiFetch } from "../api/client.ts";
