/* The one shape a hook returns.
 *
 * A discriminated union rather than `{ data, error, isLoading }`, so a component cannot
 * render a state the server never produced. That matters more here than in most products,
 * because there is no spinner to paper over an ambiguous state: every state has to be a
 * real, static rendering. */

import type { SWRResponse } from "swr";

import type { Problem } from "./problem";

export type Resource<T> =
  { status: "loading" } | { status: "error"; problem: Problem } | { status: "ready"; data: T };

/* Error wins over stale data. A hook that needs to keep the previous rendering while a
 * refetch fails owns that decision itself, because it is the only thing that knows whether
 * the stale value is still true. */
export function toResource<T>(result: SWRResponse<T, Problem>): Resource<T> {
  if (result.error !== undefined) return { status: "error", problem: result.error };
  if (result.data === undefined) return { status: "loading" };
  return { status: "ready", data: result.data };
}
