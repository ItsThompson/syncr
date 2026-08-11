/* The declarations every fixture is built from, each one a real request to the route that owns it.
 *
 * SEEDED THROUGH THE HTTP API, not through SQL and not through the repositories. Two reasons, and
 * the second is the one that matters. A SQL seed restates the schema, so it drifts the first time a
 * column moves and it can write a row the product cannot: the drill's own seed file says as much at
 * its top. And a fixture written through the API is a fixture whose every value passed the same
 * validation a user's would, so a scenario that observes something can only be observing behaviour
 * rather than a shape the production wiring could never produce.
 *
 * Every wall time here is in the tenant's home zone, which the settings declaration sets first.
 *
 * THIS LAYER IMPORTS ONE THING FROM THE HARNESS LAYER, `awaitTerminal`, and the direction is deliberate
 * rather than accidental. A sync is an operation, so a declaration that returns before it has completed is
 * a declaration whose effects are not there yet, and the wait belongs where the declaration is. The two
 * layers are otherwise separable: nothing in `harness/` imports from here.
 */

import type { ApiClient } from "../api/client.ts";
import { HOME_ZONE } from "../config.ts";
import { awaitTerminal } from "../harness/week.ts";

export type Identified = { readonly id: string };

export type AreaSpec = {
  readonly name: string;
  readonly budgetPercent: number;
  readonly floorHours: number;
};

export type Areas = Readonly<Record<string, string>>;

/** The home zone, the visible window, and the review cadence: the settings a plan is read against. */
export const declareSettings = async (client: ApiClient): Promise<void> => {
  await client.patch("/api/v1/settings", {
    homeZone: HOME_ZONE,
    dayStart: "06:00:00",
    dayEnd: "23:30:00",
    visibleHours: 17,
    reviewCadence: "on_demand",
  });
};

/** Every Area, answered as a name-to-id map so a fixture never holds a raw identifier.
 *
 * `POST /areas` answers an `AreaView`, which is the Area beside its ramp reading rather than the Area
 * alone, because the screen that creates one shows both. */
export const declareAreas = async (
  client: ApiClient,
  specs: readonly AreaSpec[],
): Promise<Areas> => {
  const created: Record<string, string> = {};
  for (const spec of specs) {
    const view = await client.post<{ readonly area: Identified }>("/api/v1/areas", {
      name: spec.name,
      budgetPercent: spec.budgetPercent,
      floorHours: spec.floorHours,
      parentId: null,
    });
    created[spec.name] = view.area.id;
  }
  return created;
};

/** One day shape, its template, and that shape on all seven weekdays. */
export const declareOneDayShape = async (
  client: ApiClient,
  name: string,
): Promise<{ readonly dayTypeId: string; readonly templateId: string }> => {
  const dayType = await client.post<Identified>("/api/v1/day-types", { name });
  const template = await client.post<Identified>("/api/v1/templates", {
    dayTypeId: dayType.id,
    name: `${name} template`,
  });
  await client.put("/api/v1/week-pattern", {
    monday: dayType.id,
    tuesday: dayType.id,
    wednesday: dayType.id,
    thursday: dayType.id,
    friday: dayType.id,
    saturday: dayType.id,
    sunday: dayType.id,
  });
  return { dayTypeId: dayType.id, templateId: template.id };
};

export type RoutineSpec = {
  readonly title: string;
  readonly targetTime: string;
  readonly durationMinutes: number;
  readonly minDurationMinutes?: number;
  readonly flexBandMinutes?: number;
};

/** A routine, and the concrete template entry that puts it on every day of the shape. */
export const declareRoutine = async (
  client: ApiClient,
  templateId: string,
  spec: RoutineSpec,
): Promise<string> => {
  const routine = await client.post<Identified>("/api/v1/routines", {
    title: spec.title,
    targetTime: spec.targetTime,
    durationMinutes: spec.durationMinutes,
    minDurationMinutes: spec.minDurationMinutes ?? null,
    flexBandMinutes: spec.flexBandMinutes ?? 0,
  });
  await client.post(`/api/v1/templates/${templateId}/entries`, {
    kind: "concrete",
    bindingTarget: "routine",
    bindingRef: routine.id,
    areaId: null,
    targetTime: spec.targetTime,
    durationMinutes: spec.durationMinutes,
    flexBandMinutes: spec.flexBandMinutes ?? 0,
  });
  return routine.id;
};

export type SlotSpec = {
  readonly areaId: string;
  readonly targetTime: string;
  readonly durationMinutes: number;
  readonly flexBandMinutes?: number;
};

/** An Area slot: a declared time and duration whose content the solve decides. */
export const declareSlot = async (
  client: ApiClient,
  templateId: string,
  spec: SlotSpec,
): Promise<string> => {
  const entry = await client.post<Identified>(`/api/v1/templates/${templateId}/entries`, {
    kind: "slot",
    areaId: spec.areaId,
    targetTime: spec.targetTime,
    durationMinutes: spec.durationMinutes,
    flexBandMinutes: spec.flexBandMinutes ?? 0,
  });
  return entry.id;
};

export type HabitSpec = {
  readonly title: string;
  readonly areaId: string;
  readonly minDurationMinutes: number;
  readonly maxDurationMinutes?: number;
  readonly timesPerWeek?: number;
  readonly bindingSource?: "fixed" | "rotation" | "queue";
  readonly variants?: readonly string[];
  readonly missPolicy?: "forgive" | "debt" | "escalate";
  readonly debtCapPeriods?: number;
};

export const declareHabit = async (client: ApiClient, spec: HabitSpec): Promise<string> => {
  const habit = await client.post<Identified>("/api/v1/habits", {
    title: spec.title,
    areaId: spec.areaId,
    minDurationMinutes: spec.minDurationMinutes,
    maxDurationMinutes: spec.maxDurationMinutes ?? null,
    bindingSource: spec.bindingSource ?? "fixed",
    variants: spec.variants ?? [],
    missPolicy: spec.missPolicy ?? "forgive",
    debtCapPeriods: spec.debtCapPeriods ?? 2,
    cadence: { kind: "times_per_week", timesPerWeek: spec.timesPerWeek ?? 1, approxDays: null },
  });
  return habit.id;
};

export type TaskSpec = {
  readonly title: string;
  readonly areaId: string;
  readonly estimateMinutes: number;
  /** An instant carrying an offset, or null for no deadline. A day is not one: see `utcMidnightOn`. */
  readonly deadline?: string | null;
  readonly minChunkMinutes?: number | null;
  readonly priority?: "low" | "normal" | "high" | "urgent";
  readonly splittable?: boolean;
};

export const declareTask = async (client: ApiClient, spec: TaskSpec): Promise<string> => {
  const task = await client.post<Identified>("/api/v1/tasks", {
    title: spec.title,
    areaId: spec.areaId,
    estimateMinutes: spec.estimateMinutes,
    deadline: spec.deadline ?? null,
    minChunkMinutes: spec.minChunkMinutes ?? null,
    priority: spec.priority ?? "normal",
    splittable: spec.splittable ?? true,
  });
  return task.id;
};

export type AnchorTypeSpec = {
  readonly name: string;
  readonly matchTitleContains: string;
  readonly prepAreaId?: string | null;
  readonly prepLeadMinutes?: number;
  readonly prepDurationMinutes?: number;
  readonly transitAreaId?: string | null;
  readonly transitLeadMinutes?: number | null;
  readonly transitDurationMinutes?: number;
  readonly returnTransitMinutes?: number;
  readonly postBufferMinutes?: number;
  readonly postScope?: "none" | "all" | "areas";
  readonly forbiddenAreaIds?: readonly string[];
};

export const declareAnchorType = async (
  client: ApiClient,
  spec: AnchorTypeSpec,
): Promise<string> => {
  const type = await client.post<Identified>("/api/v1/anchor-types", {
    name: spec.name,
    matchTitleContains: spec.matchTitleContains,
    matchSourceId: null,
    prepAreaId: spec.prepAreaId ?? null,
    prepLeadMinutes: spec.prepLeadMinutes ?? 0,
    prepDurationMinutes: spec.prepDurationMinutes ?? 0,
    transitAreaId: spec.transitAreaId ?? null,
    transitLeadMinutes: spec.transitLeadMinutes ?? null,
    transitDurationMinutes: spec.transitDurationMinutes ?? 0,
    returnTransitMinutes: spec.returnTransitMinutes ?? 0,
    postBufferMinutes: spec.postBufferMinutes ?? 0,
    postScope: spec.postScope ?? "none",
    forbiddenAreaIds: spec.forbiddenAreaIds ?? [],
  });
  return type.id;
};

/** An ICS source pointing at the mocked provider, synced to completion so its anchors exist.
 *
 * THE WAIT IS NOT OPTIONAL. A sync is an operation the worker picks up on its own five-second cadence, so
 * returning as soon as it is enqueued makes every ordering a fixture states afterwards a race: the
 * reference week claims its anchors exist BEFORE the maintainer draws the plan around them, and the tick
 * that materializes runs two to four seconds later. That ordering is the anchor conflict the fixture
 * table names, and it was asserted in prose and not in code. */
export const declareIcsSource = async (
  client: ApiClient,
  displayName: string,
  feedUrl: string,
  { sync = true }: { readonly sync?: boolean } = {},
): Promise<string> => {
  const source = await client.post<Identified>("/api/v1/calendar-sources", {
    provider: "ics",
    displayName,
    externalId: feedUrl,
  });
  if (!sync) return source.id;

  const enqueued = await client.post<Identified>(`/api/v1/calendar-sources/${source.id}/sync`);
  const settled = await awaitTerminal(client, enqueued.id);
  if (settled.status !== "succeeded") {
    throw new Error(
      `syncing ${displayName} from ${feedUrl} ended ${settled.status}: ${settled.statement} ` +
        JSON.stringify(settled.error),
    );
  }
  return source.id;
};
