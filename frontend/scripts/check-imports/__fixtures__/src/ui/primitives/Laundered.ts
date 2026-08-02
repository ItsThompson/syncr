/* Fixture: a primitive that fetches through the innocent-looking first hop.
 *
 * `../../lib/handy` is permitted to every zone. It re-exports the fetch client. Checking only the
 * first hop calls this file clean. */

import { apiFetch } from "../../lib/handy.ts";

export async function fetchViaLib(): Promise<unknown> {
  return apiFetch("/v1/areas");
}
