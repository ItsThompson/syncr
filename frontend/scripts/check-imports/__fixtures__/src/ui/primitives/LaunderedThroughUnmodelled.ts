/* Fixture: a primitive fetching through a permitted conduit into an unmodelled directory.
 *
 * Both hops looked clean. `../../lib/via-unmodelled` is a `lib/` import, which every zone may make, and
 * the file it reaches sits in a directory no rule names. Two silences compose into a fetching
 * primitive. */

import { probeReadiness } from "../../lib/via-unmodelled.ts";

export async function fetchViaUnmodelled(): Promise<unknown> {
  return probeReadiness();
}
