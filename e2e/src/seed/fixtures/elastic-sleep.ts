/* `elastic_sleep`: a sleep routine with a minimum below its target, and a week that needs the give.
 *
 * The routine's numbers are NOT written here. `syncr_domain.fixtures.elastic_sleep` already states
 * them, and the domain and api suites assert against those literals, so this reads them out of the
 * package instead of holding a second copy that would stop straddling the same gap the day the
 * fixture's minimum moved.
 *
 * What this fixture adds is the week that needs the give, which the domain fixture deliberately does
 * not build: its own docstring says the gap "is stated rather than built", because what produces a
 * shortfall is a floor, a deadline or a declared span, and each of those is a stored row in another
 * package. Here it is a deadline: a task far larger than the capacity before it, in the week every
 * scenario drives, so the shortfall is a capacity fact rather than a passed deadline.
 *
 * The second routine is inelastic on purpose. S26's observation is that `reduce_routine` is offered
 * for sleep AND FOR NO OTHER ROUTINE, and without a routine whose minimum equals its target there is
 * nothing for that half of the claim to exclude.
 */

import type { ApiClient } from "../../api/client.ts";
import { dateIn, WEDNESDAY } from "../../api/weeks.ts";
import { domainConstants } from "../../harness/compose.ts";
import { planWeek } from "../../harness/subject-weeks.ts";
import {
  declareAreas,
  declareOneDayShape,
  declareRoutine,
  declareSettings,
  declareSlot,
  declareTask,
} from "../declarations.ts";

const AREAS = [
  { name: "Career", budgetPercent: 60, floorHours: 9 },
  { name: "Fitness", budgetPercent: 20, floorHours: 2 },
] as const;

/* Fifty hours due by Wednesday. The plan week is entirely in the future, so the capacity before that
 * deadline is three days of the visible window less the frame, which is comfortably under fifty
 * however the week falls: the shortfall is therefore present on every day the suite might run. */
const OVERSIZED_ESTIMATE_MINUTES = 3000;

export const seedElasticSleep = async (client: ApiClient): Promise<void> => {
  const sleep = (await domainConstants()).elastic_sleep;

  await declareSettings(client);
  const areas = await declareAreas(client, AREAS);
  const { templateId } = await declareOneDayShape(client, "Everyday");

  await declareRoutine(client, templateId, {
    title: sleep.title,
    targetTime: sleep.targetTime,
    durationMinutes: sleep.durationMinutes,
    minDurationMinutes: sleep.minDurationMinutes,
  });
  await declareRoutine(client, templateId, {
    title: "Dinner",
    targetTime: "19:00:00",
    durationMinutes: 60,
    minDurationMinutes: 60,
  });
  await declareSlot(client, templateId, {
    areaId: areas.Career!,
    targetTime: "09:00:00",
    durationMinutes: 120,
  });

  await declareTask(client, {
    title: "Dissertation chapter",
    areaId: areas.Career!,
    estimateMinutes: OVERSIZED_ESTIMATE_MINUTES,
    deadline: dateIn(planWeek(), WEDNESDAY),
    minChunkMinutes: 60,
    priority: "urgent",
  });

  console.log(
    `elastic_sleep: ${sleep.title} is ${sleep.durationMinutes} with a minimum of ` +
      `${sleep.minDurationMinutes}, so each night has ${sleep.giveMinutes} minutes to give`,
  );
};
