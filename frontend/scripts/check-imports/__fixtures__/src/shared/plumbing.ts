/* Fixture: the directory nobody added to the model.
 *
 * The plant is verbatim in shape. `src/shared/` is not in `AREAS`, so `areaOf` returned null for it,
 * and null meant permitted at both call sites AND stopped the transitive walk. A `ui/domain`
 * component reaching this file fetched in dev, in test and in production while all seven checks,
 * oxlint, tsc, prettier and `vite build` were green.
 *
 * Adding `src/hooks/`, `src/utils/` or `src/shared/` is an ordinary thing to do, and nothing in the
 * repository said not to. */

import { apiFetch } from "../api/client.ts";

export async function probeReadiness(): Promise<unknown> {
  return apiFetch("/readyz");
}
