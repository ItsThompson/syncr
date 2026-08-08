/* `tight_capacity`: a week whose declared floors sit just inside its remaining capacity.
 *
 * THE FIXTURE THREE STATED GAPS SHARE. `reference_week` holds 92 hours of discretionary time against
 * eight hours of declared floor, so a floor reservation that nets nothing still fits: the B1 assertions
 * have nothing to discriminate and were measured green under a bite that reverted the netting rule.
 * S25 needs the same thing from the other direction, a week where pinning two hours of unrelated work
 * moves a shortfall. And a verdict that one mutation can flip is what makes a session-attributed
 * infeasibility episode constructible at all.
 *
 * HOW THE WEEK IS MADE TIGHT: by the FRAME, not by an oversized demand. Two routines cover twenty and a
 * half hours of every day, so three and a half hours a day are discretionary, and the Area slots
 * declared in them are what the floors are met by. That is the shape B1 is about: a healthy solved week
 * is one whose floors are met by UNPINNED solver-placed blocks.
 *
 * The arithmetic is stated here and asserted by the scenarios rather than restated by them:
 *
 *   frame per day        Sleep 22:00 + 9h, Work 09:00 + 11h30m      20h30m
 *   discretionary        3h30m a day, seven days                     1470 minutes
 *   slots declared       Career 07:00 + 90m, Fitness 20:30 + 90m     1260 minutes
 *   floors declared      Career 8h, Fitness 8h                        960 minutes
 *   free once solved     1470 less the placements                     210 minutes
 *
 * So the correct reservation is zero, because every floor minute is already placed, and 0 fits in 210.
 * A reservation that netted immovable placements only would be 960 against 210 and would report a
 * shortfall of 750 on a week that is fully scheduled, which is the defect B1 names.
 */

import type { ApiClient } from "../../api/client.ts";
import { dateIn, WEDNESDAY } from "../../api/weeks.ts";
import { planWeek } from "../../harness/subject-weeks.ts";
import {
  declareAreas,
  declareOneDayShape,
  declareRoutine,
  declareSettings,
  declareSlot,
  declareTask,
} from "../declarations.ts";

/* Two Areas with equal floors, each larger than half the free capacity, so neither can be met without
 * the other's slots also being filled. */
const AREAS = [
  { name: "Career", budgetPercent: 45, floorHours: 8 },
  { name: "Fitness", budgetPercent: 45, floorHours: 8 },
] as const;

export const CAREER_FLOOR_MINUTES = 8 * 60;
export const FITNESS_FLOOR_MINUTES = 8 * 60;
export const DEADLINE_TASK = "Lab report";

export const seedTightCapacity = async (client: ApiClient): Promise<void> => {
  await declareSettings(client);
  const areas = await declareAreas(client, AREAS);
  const { templateId } = await declareOneDayShape(client, "Everyday");

  // The frame. Nine hours of sleep and eleven and a half of committed work, which between them leave
  // 07:00 to 09:00 and 20:30 to 22:00 discretionary on every date.
  await declareRoutine(client, templateId, {
    title: "Sleep",
    targetTime: "22:00:00",
    durationMinutes: 540,
  });
  await declareRoutine(client, templateId, {
    title: "Work",
    targetTime: "09:00:00",
    durationMinutes: 690,
  });

  // The slots the floors are met through, one per discretionary window.
  await declareSlot(client, templateId, {
    areaId: areas.Career!,
    targetTime: "07:00:00",
    durationMinutes: 90,
  });
  await declareSlot(client, templateId, {
    areaId: areas.Fitness!,
    targetTime: "20:30:00",
    durationMinutes: 90,
  });

  // Enough content per Area to fill every one of its slots, so a solved week's floors are met.
  await declareTask(client, {
    title: "Coursework",
    areaId: areas.Career!,
    estimateMinutes: 900,
    minChunkMinutes: 90,
  });
  await declareTask(client, {
    title: "Training plan",
    areaId: areas.Fitness!,
    estimateMinutes: 900,
    minChunkMinutes: 90,
  });
  // A deadline mid-week, so the DEADLINE CHECK has a demand to read. Under the correct reservation it
  // is met and the backlog's at-risk column is empty; under the reverted one every deadline shortfall
  // is inflated by the whole of both already-scheduled floors, and this task is marked at risk.
  await declareTask(client, {
    title: DEADLINE_TASK,
    areaId: areas.Career!,
    estimateMinutes: 180,
    minChunkMinutes: 90,
    deadline: dateIn(planWeek(), WEDNESDAY),
    priority: "high",
  });

  console.log(
    `tight_capacity: 1470 discretionary minutes a week against floors of ` +
      `${CAREER_FLOOR_MINUTES} and ${FITNESS_FLOOR_MINUTES}`,
  );
};
