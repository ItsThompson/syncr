/* The tenant's settings, and the travel overrides that bend the zone inside a date range.
 *
 * TWO RESOURCES RATHER THAN ONE, because the api serves two and they change independently: a visible-hours
 * change touches the settings row and no override, and declaring a trip touches an override and no setting.
 *
 * A TRAVEL WRITE INVALIDATES THE SETTINGS TOO, and that is the one non-obvious invalidation here. The settings
 * response carries `activeZone`, resolved through the override covering today, so declaring or removing an
 * override that covers today changes a field on a resource the request never named. Leaving it out would leave
 * the screen stating a zone that is no longer active, which is exactly what US-TZ-02 forbids.
 *
 * THE SLEEP FLOOR IS NOT HERE. It is `minDurationMinutes` on the sleep routine, and the Settings screen reaches
 * it through `useRoutineEdit`. There is one home for the value and this is not it. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { settingsKey, travelOverridesKey } from "../keys";
import { apply, read } from "./request";
import { useWrite, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type Settings = components["schemas"]["SettingsResponse"];
export type SettingsPatchBody = components["schemas"]["SettingsPatchRequest"];
export type TravelOverride = components["schemas"]["TravelOverrideResponse"];
export type TravelOverrideBody = components["schemas"]["TravelOverrideRequest"];

/** A removal names its row in the path, so the id arrives with the call rather than with the hook. */
export interface TravelOverrideRemoval {
  readonly overrideId: string;
}

async function readSettings(): Promise<Settings> {
  return read(() => client.GET("/api/v1/settings"));
}

async function readTravelOverrides(): Promise<readonly TravelOverride[]> {
  const { overrides } = await read(() => client.GET("/api/v1/settings/travel-overrides"));
  return overrides;
}

export function useSettings(): Resource<Settings> {
  return toResource(useSWR<Settings, Problem>(settingsKey(), readSettings));
}

export function useTravelOverrides(): Resource<readonly TravelOverride[]> {
  return toResource(
    useSWR<readonly TravelOverride[], Problem>(travelOverridesKey(), readTravelOverrides),
  );
}

/** Visible hours, day bounds, the home zone, and the review cadence. An omitted field is left alone. */
export function useSettingsPatch(): Write<SettingsPatchBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: SettingsPatchBody) => {
    const refusal = await apply(() => client.PATCH("/api/v1/settings", { body }));
    if (refusal !== null) return refusal;
    await mutate(settingsKey());
    return null;
  });
}

export function useTravelOverrideDeclaration(): Write<TravelOverrideBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: TravelOverrideBody) => {
    const refusal = await apply(() => client.POST("/api/v1/settings/travel-overrides", { body }));
    if (refusal !== null) return refusal;
    await mutate(travelOverridesKey());
    await mutate(settingsKey());
    return null;
  });
}

export function useTravelOverrideRemoval(): Write<TravelOverrideRemoval> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ overrideId }: TravelOverrideRemoval) => {
    const refusal = await apply(() =>
      client.DELETE("/api/v1/settings/travel-overrides/{override_id}", {
        params: { path: { override_id: overrideId } },
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(travelOverridesKey());
    await mutate(settingsKey());
    return null;
  });
}
