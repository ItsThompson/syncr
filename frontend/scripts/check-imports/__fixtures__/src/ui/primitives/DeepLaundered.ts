/* Fixture: a primitive reaching the fetch client through TWO conduit hops, and a primitive sitting on
 * an import cycle.
 *
 * The cycle half must stay clean while the chain half is refused, which is the pair that separates a
 * terminating walk from one that either spins or gives up. */

import { apiFetch } from "../../lib/deep.ts";
import { fromA } from "../../lib/loop-a.ts";

export async function fetchTwoHopsAway(): Promise<unknown> {
  return apiFetch(`/v1/areas?${fromA}`);
}
