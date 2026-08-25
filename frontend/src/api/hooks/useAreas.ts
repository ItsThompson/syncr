/* The Areas a tenant has declared, and how much of the sealed ramp they are using.
 *
 * The ramp reading travels with the list because it is a fact about the list rather than about any one
 * Area. A surface that renders Area chips reads how much of the sealed ramp is in use from it, and no
 * screen can render a sentence the api does not send: no step of the ramp is ever shared, so there is no
 * shared-step sentence to carry. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { areasKey, budgetReviewKey } from "../keys";
import { apply, read } from "./request";
import { useWrite, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type Area = components["schemas"]["AreaResponse"];
export type Ramp = components["schemas"]["RampReading"];
export type AreaDeclarationBody = components["schemas"]["AreaCreateRequest"];

export interface Areas {
  readonly areas: readonly Area[];
  readonly ramp: Ramp;
}

async function readAreas(): Promise<Areas> {
  const { areas, ramp } = await read(() => client.GET("/api/v1/areas"));
  return { areas, ramp };
}

export function useAreas(): Resource<Areas> {
  return toResource(useSWR<Areas, Problem>(areasKey(), readAreas));
}

/**
 * Declaring an Area.
 *
 * NO PIGMENT IS SENT AND NONE CAN BE. The request shape has no field for one: creation deals the next step of
 * the sealed ramp, so what the caller learns is what it was dealt, by re-reading the list. That is also how
 * the ramp reading arrives, which says how many of the twelve are in use.
 *
 * The review is invalidated with the list, because an Area is a category of the composition and a share of
 * the budget: a new one changes both, and the review's figures are computed from them.
 */
export function useAreaDeclaration(period: string): Write<AreaDeclarationBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: AreaDeclarationBody) => {
    const refusal = await apply(() => client.POST("/api/v1/areas", { body }));
    if (refusal !== null) return refusal;
    await mutate(areasKey());
    await mutate(budgetReviewKey(period));
    return null;
  });
}
