/* Fixture: a conduit hop into a directory the model does not name.
 *
 * `lib/` is readable from every zone, and this file re-exports from `src/shared/`, which `AREAS` does
 * not list. The walk used to stop dead here, because an unmodelled area returned null and null was the
 * same value a package returns. So the chain went dark one hop before the fetch client. */

export { probeReadiness } from "../shared/plumbing.ts";
