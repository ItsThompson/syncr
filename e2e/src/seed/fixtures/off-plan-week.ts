/* `off_plan_week`: a week with a Friday-to-Monday off-plan span containing one pin.
 *
 * The span is declared with `keepFrame` false, which is the case S16 opens with: nothing inside it,
 * routines included. A scenario that wants the other half patches the period to `keepFrame` true and
 * observes routines reappear while nothing else does.
 *
 * The pin inside the span is what proves the span is a scheduling rule rather than a blackout: a pin
 * is honored wherever it is placed. It is made by the scenario that reads it, because a pin needs a
 * block and a block needs a materialized week, which is the step after this one.
 */

import type { ApiClient } from "../../api/client.ts";
import { civilDateIn, dateIn, FRIDAY, isoWeekOf, MONDAY, isoWeekShift } from "../../api/weeks.ts";
import { HOME_ZONE } from "../../config.ts";
import { declareBaseline } from "../baseline.ts";
import { declareRoutine, declareSlot, declareTask } from "../declarations.ts";
import { instantAt } from "../../api/weeks.ts";

export const seedOffPlanWeek = async (client: ApiClient): Promise<void> => {
  const { areas, templateId } = await declareBaseline(client);

  await declareRoutine(client, templateId, {
    title: "Sleep",
    targetTime: "23:00:00",
    durationMinutes: 480,
  });
  await declareRoutine(client, templateId, {
    title: "Wake Up",
    targetTime: "07:00:00",
    durationMinutes: 15,
  });
  await declareSlot(client, templateId, {
    areaId: areas.Career!,
    targetTime: "09:00:00",
    durationMinutes: 90,
  });
  await declareSlot(client, templateId, {
    areaId: areas.Fitness!,
    targetTime: "18:00:00",
    durationMinutes: 60,
  });
  await declareTask(client, {
    title: "Career reading",
    areaId: areas.Career!,
    estimateMinutes: 180,
    minChunkMinutes: 30,
  });

  const thisWeek = isoWeekOf(civilDateIn(HOME_ZONE));
  const start = instantAt(dateIn(thisWeek, FRIDAY), "14:00:00", HOME_ZONE);
  const end = instantAt(dateIn(isoWeekShift(thisWeek, 1), MONDAY), "09:00:00", HOME_ZONE);

  await client.post("/api/v1/off-plan", {
    start,
    end,
    keepFrame: false,
    label: "Away for the weekend",
  });

  console.log(`off_plan_week: ${start} to ${end}, keepFrame false`);
};
