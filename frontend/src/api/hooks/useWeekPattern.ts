/* The week pattern: which day type each weekday uses.
 *
 * A 404 IS AN ANSWER, NOT A FAILURE. The api answers 404 until a pattern is declared, deliberately: the
 * alternative was a 200 carrying seven nulls, which would make every consumer narrow a shape that is
 * either complete or absent. This route takes no path parameter, so a 404 can mean nothing else, and
 * `null` is the reading the form starts empty from.
 *
 * A PATTERN IS REPLACED WHOLE, which is why the write is a PUT and its body carries all seven weekdays.
 * There is no per-weekday merge rule to express: a weekday with no day type materializes nothing, so a
 * request naming three weekdays would have to mean something about the other four.
 *
 * The pattern maps every weekday, so replacing it reaches every future week. That is the api's own
 * invalidation and this hook does not model it; what it invalidates is the client's copy of the pattern. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { weekPatternKey } from "../keys";
import { apply } from "./request";
import { idempotentHeaders, useWrite, type Write } from "./useWrite";
import {
  toProblem,
  toResource,
  unreachableProblem,
  type Problem,
  type Resource,
} from "../../contract";
import type { components } from "../schema";

export type WeekPattern = components["schemas"]["WeekPatternResponse"];
export type WeekPatternBody = components["schemas"]["WeekPatternRequest"];

const NOT_DECLARED = 404;

async function readWeekPattern(): Promise<WeekPattern | null> {
  const { data, error, response } = await client
    .GET("/api/v1/week-pattern")
    .catch((cause: unknown) => {
      throw unreachableProblem(cause);
    });
  if (response.status === NOT_DECLARED) return null;
  if (data === undefined) throw toProblem(error, response);
  return data;
}

/** The declared pattern, or null when the tenant has not declared one yet. */
export function useWeekPattern(): Resource<WeekPattern | null> {
  return toResource(useSWR<WeekPattern | null, Problem>(weekPatternKey(), readWeekPattern));
}

export function useWeekPatternDeclaration(): Write<WeekPatternBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: WeekPatternBody) => {
    const refusal = await apply(() =>
      client.PUT("/api/v1/week-pattern", { headers: idempotentHeaders(), body }),
    );
    if (refusal !== null) return refusal;
    await mutate(weekPatternKey());
    return null;
  });
}
