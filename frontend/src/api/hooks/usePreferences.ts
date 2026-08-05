/* An Area's placement preference: the set the Areas table draws, and the two writes that author one.
 *
 * ONE HOOK FOR THE WHOLE SET, NOT ONE PER AREA. The api addresses a preference by its owner, so reading them
 * is a request each; what a SURFACE needs is the set, because the Areas table draws a Preference cell on
 * every row and a table cannot draw two thirds of a column. A hook per Area is also not expressible: the
 * number of Areas is data, and React resolves hooks by call order.
 *
 * A MISSING PREFERENCE IS AN ANSWER. The routes 404 on the OWNER and never on the preference, so every Area
 * answers 200 and `declared` is null for one that has authored none. Nothing here treats that as an error.
 *
 * THE CAP IS ON THE AREA'S REQUEST SHAPE AND ON NO OTHER. A daily cap is a hard constraint and an Area's
 * alone, so an override's request shape has no field for one and sending it is a stated 422. That is the api's
 * rule; what this file adds is that only the Area write is exposed, because the Areas screen authors an
 * Area's preference and nothing else. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { areaPreferencesKey, budgetReviewKey } from "../keys";
import { apply, read } from "./request";
import { useWrite, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type Preference = components["schemas"]["PreferenceResponse"];
export type EffectivePreference = components["schemas"]["EffectivePreferenceResponse"];
export type PreferenceWindow = components["schemas"]["TimeWindowResponse"];
export type PreferenceStrength = components["schemas"]["PreferenceStrength"];
export type AreaPreferenceBody = components["schemas"]["AreaPreferenceRequest"];

/** Every Area's preference, by Area id. An Area answering 200 with no declaration is a member. */
export type PreferenceSet = Readonly<Record<string, Preference>>;

/** What one edit of an Area's preference sends: which Area, and the whole preference. */
export interface AreaPreferenceEdit {
  readonly areaId: string;
  readonly preference: AreaPreferenceBody;
}

/** Which Area's preference to remove. Removing one an Area never declared is a 200, not a 404. */
export interface AreaPreferenceRemoval {
  readonly areaId: string;
}

async function readPreference(areaId: string): Promise<Preference> {
  return read(() =>
    client.GET("/api/v1/areas/{area_id}/preference", { params: { path: { area_id: areaId } } }),
  );
}

async function readPreferences(areaIds: readonly string[]): Promise<PreferenceSet> {
  const found = await Promise.all(areaIds.map((areaId) => readPreference(areaId)));
  return Object.fromEntries(areaIds.map((areaId, index) => [areaId, found[index]]));
}

/**
 * Every named Area's preference, read together.
 *
 * `null` for `areaIds` is how a caller says the Area list has not arrived: the set is keyed by the ids, so
 * fetching before they are known would read a set the table could not use. SWR treats a null key as "do not
 * fetch", which leaves the reading pending, which is what it is.
 */
export function useAreaPreferences(areaIds: readonly string[] | null): Resource<PreferenceSet> {
  return toResource(
    useSWR<PreferenceSet, Problem>(
      areaIds === null ? null : areaPreferencesKey(areaIds),
      areaIds === null ? null : () => readPreferences(areaIds),
    ),
  );
}

function useInvalidation(areaIds: readonly string[], period: string): () => Promise<void> {
  const { mutate } = useSWRConfig();

  return async () => {
    await mutate(areaPreferencesKey(areaIds));
    await mutate(budgetReviewKey(period));
  };
}

/**
 * Declaring an Area's preference, whole.
 *
 * `PUT` rather than `PATCH`, because a preference replaces wholly: a field left out is null afterwards rather
 * than unchanged, and there is no merge rule to express. The review is invalidated as well as the set,
 * because a preference is a solve input and the figures the review reports are computed from one.
 */
export function useAreaPreferenceDeclaration(
  areaIds: readonly string[],
  period: string,
): Write<AreaPreferenceEdit> {
  const invalidate = useInvalidation(areaIds, period);

  return useWrite(async ({ areaId, preference }: AreaPreferenceEdit) => {
    const refusal = await apply(() =>
      client.PUT("/api/v1/areas/{area_id}/preference", {
        params: { path: { area_id: areaId } },
        body: preference,
      }),
    );
    if (refusal !== null) return refusal;
    await invalidate();
    return null;
  });
}

/** Removing an Area's preference. The api answers with the resulting state, so the set is re-read. */
export function useAreaPreferenceRemoval(
  areaIds: readonly string[],
  period: string,
): Write<AreaPreferenceRemoval> {
  const invalidate = useInvalidation(areaIds, period);

  return useWrite(async ({ areaId }: AreaPreferenceRemoval) => {
    const refusal = await apply(() =>
      client.DELETE("/api/v1/areas/{area_id}/preference", {
        params: { path: { area_id: areaId } },
      }),
    );
    if (refusal !== null) return refusal;
    await invalidate();
    return null;
  });
}
