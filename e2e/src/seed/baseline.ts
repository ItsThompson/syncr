/* The declarations a fixture needs before it can say anything of its own.
 *
 * The least a plan can exist from is settings, Areas, a day shape and a week pattern; the weight set
 * arrives with the tenant. Every fixture but `reference_week` starts here and then declares only the
 * thing it is ABOUT, so what a scenario observes is attributable to that thing rather than to
 * whatever else a full week happens to hold.
 */

import type { ApiClient } from "../api/client.ts";
import { declareAreas, declareOneDayShape, declareSettings, type Areas } from "./declarations.ts";

/* Three Areas summing to 70%, so `Unallocated` is non-zero in every fixture that does not set out
 * to change it. Career carries a floor because a floor is what makes a week refusable. */
export const BASELINE_AREAS = [
  { name: "Career", budgetPercent: 30, floorHours: 3 },
  { name: "Fitness", budgetPercent: 20, floorHours: 2 },
  { name: "Study", budgetPercent: 20, floorHours: 0 },
] as const;

export type Baseline = {
  readonly areas: Areas;
  readonly dayTypeId: string;
  readonly templateId: string;
};

export const declareBaseline = async (client: ApiClient): Promise<Baseline> => {
  await declareSettings(client);
  const areas = await declareAreas(client, BASELINE_AREAS);
  const shape = await declareOneDayShape(client, "Everyday");
  return { areas, ...shape };
};
