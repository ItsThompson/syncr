/* Fixture: a kit component fetching through a directory the zone model does not name.
 *
 * The specifier names no denied area, so oxlint's globs are silent. The resolved file sits in
 * `src/shared/`, which `AREAS` does not list, so the resolver used to be silent too. Both checks said
 * the fence held while the handler went into the production chunk. */

import { probeReadiness } from "../../../shared/plumbing.ts";

export async function Unmodelled(): Promise<unknown> {
  return probeReadiness();
}
