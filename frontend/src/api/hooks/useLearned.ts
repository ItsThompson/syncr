/* THE LEARNED SCREEN'S TWO READS, AND THE ONE WRITE THAT PUTS A VERSION IN FORCE.
 *
 * TWO READS BECAUSE THEY ANSWER TWO QUESTIONS. `/learned` is the parameters and their maturity, which is what the
 * table renders; `/weight-sets` is the versions, which is what a comparison and a revert address. Nesting the second
 * under the first would make the screen's own path the address of a row it does not render.
 *
 * ACTIVATION IS ONE ACTION AND IT IS THE SAME ONE A REVERT IS. There is no separate revert route: putting version 1
 * back in force is activating version 1, so a rollback is the flip nobody has to build twice. `US-LEARN-07`.
 *
 * WHAT AN ACTIVATION INVALIDATES IS NAMED, INCLUDING THE WEEKS THE SERVER SAYS IT RE-SOLVED. The response carries
 * them, so the invalidation is exact rather than blanket: a week the activation did not touch is not refetched, and a
 * week it did is, without this hook having to guess which weeks are in the future. A blanket revalidation would
 * refetch every screen's data because a weight set changed, which is slow and is a source of flicker on a surface
 * with no animation to hide it. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { learnedKey, weekKey, weightSetsKey } from "../keys";
import { answered, read } from "./request";
import { useWrite, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type Learned = components["schemas"]["LearnedResponse"];
export type LearnedParameter = components["schemas"]["ParameterResponse"];
export type WeightSets = components["schemas"]["WeightSetsResponse"];
export type WeightSet = components["schemas"]["WeightSetResponse"];
export type Activated = components["schemas"]["ActivatedResponse"];

/** Which version to put in force. A revert names an earlier one; nothing else differs. */
export interface ActivationBody {
  readonly version: number;
}

async function readLearned(): Promise<Learned> {
  return read(() => client.GET("/api/v1/learned"));
}

async function readWeightSets(): Promise<WeightSets> {
  return read(() => client.GET("/api/v1/weight-sets"));
}

/** Every parameter, what it is fitted to, and how far from its gate it is. */
export function useLearned(): Resource<Learned> {
  return toResource(useSWR<Learned, Problem>(learnedKey(), readLearned));
}

/** Every version this account holds, newest first, with its origin and whether it is in force. */
export function useWeightSets(): Resource<WeightSets> {
  return toResource(useSWR<WeightSets, Problem>(weightSetsKey(), readWeightSets));
}

/**
 * Putting a version in force, which is also how a revert is made.
 *
 * The response's own week list is what gets invalidated beside the two learning keys: the server states which future
 * weeks it re-solved, so nothing here has to decide which weeks those are, and a past week's approved revision is
 * untouched and stays cached.
 */
export function useWeightSetActivation(): Write<ActivationBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ version }: ActivationBody) => {
    const result = await answered(() =>
      client.POST("/api/v1/weight-sets/{version}/activate", {
        params: { path: { version } },
      }),
    );
    if (result.problem !== null) return result.problem;
    await mutate(learnedKey());
    await mutate(weightSetsKey());
    /* The weeks the server says it re-solved, invalidated together: they are independent keys, and which of them
     * arrives first is not a fact about anything. */
    await Promise.all(result.body.resolvedWeeks.map((isoWeek) => mutate(weekKey(isoWeek))));
    return null;
  });
}
