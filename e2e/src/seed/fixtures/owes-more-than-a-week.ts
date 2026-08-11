/* `owes_more_than_a_week`: a week with no frame at all, owing more work before one deadline than any
 * week could hold. The fixture the two clock-free halves of S36 are asked about.
 *
 * WHY NO ROUTINE AND NO SLOT. S36's subject is which SPAN the verdict measures capacity over, so
 * everything else the span could be reduced by is left out: with no frame, no anchor and no declared
 * window, the week's discretionary time IS its own span, and the capacity a verdict reports before a
 * deadline beyond the week is the distance from the reading instant to the week's end. Both figures
 * are then derivable from a clock alone, which is what lets a scenario assert them as figures rather
 * than compare them to each other. Every other fixture here states a frame, and a frame makes the
 * same assertion a function of which hour the suite runs at: whether the reading instant falls inside
 * a sleep span decides whether any capacity has elapsed at all.
 *
 * WHY THE DEMAND IS LARGER THAN A WEEK. A gap this week cannot close has to be larger than the
 * capacity the week would have had if none of it had elapsed, or the gap appears on a Thursday and not
 * on a Monday and a scenario asserting it passes for the wrong reason. So the demand is one hour more
 * than the LONGEST week a zone can have -- a week whose clocks go back is 169 hours -- plus an hour of
 * overhang, and the gap it reports is the difference between the two, which stays positive at every
 * instant of every week including the two the clock changes in.
 *
 * WHY TWO TASKS AND NOT ONE. `estimateMinutes` may not exceed 10080, which is one week, and the demand
 * has to exceed one week. Two tasks in one Area sharing one deadline are ONE demand to the probe --
 * they compete for the same capacity, so it groups them per deadline and Area and names both -- so the
 * split changes the labels the gap carries and no figure.
 *
 * WHERE THE DEADLINE FALLS, AND WHY BEYOND THE WEEK. A deadline inside the week clips the capacity
 * before it to part of the span, which is a second reason for a figure to be smaller than the whole
 * week and would make the clip to `now` unattributable. Placed on the Monday that ENDS the plan week,
 * the deadline is at or after both subject weeks' last instant, so each week's capacity before it is
 * that week's whole remaining span and nothing else.
 *
 * NO FLOOR ON THE ONE AREA. A floor is a competitor the probe subtracts from the capacity before a
 * deadline, and a competitor is a third term in an arithmetic this fixture exists to keep to two.
 */

import type { ApiClient } from "../../api/client.ts";
import { dateIn, isoWeekShift, MONDAY } from "../../api/weeks.ts";
import { planWeek } from "../../harness/subject-weeks.ts";
import { declareAreas, declareOneDayShape, declareSettings, declareTask } from "../declarations.ts";

/** The Area both tasks are filed in, so their demands group into one. */
export const DEMAND_AREA = "Career";

/* A week whose clocks go back is 169 hours, so this is the most capacity any week can offer. */
const LONGEST_WEEK_MINUTES = 7 * 24 * 60 + 60;

/** More than the longest week, so the gap exists at every instant rather than late in the week. */
export const DEMAND_MINUTES = LONGEST_WEEK_MINUTES + 60;

/** The two titles the gap names, and the halves the demand is declared in. */
export const DEADLINE_TASKS = [
  "First half of the reading list",
  "Second half of the reading list",
] as const;

/** One task may not be larger than a week, so the demand is declared in equal halves. */
export const EACH_MINUTES = DEMAND_MINUTES / DEADLINE_TASKS.length;

/** The smallest piece the solver may place, which is what makes a placed block legible. */
const CHUNK_MINUTES = 60;

/** The Monday that ends the plan week: at or after the last instant of both subject weeks. */
export const deadlineDate = (): string => dateIn(isoWeekShift(planWeek(), 1), MONDAY);

export const seedOwesMoreThanAWeek = async (client: ApiClient): Promise<void> => {
  await declareSettings(client);
  const areas = await declareAreas(client, [
    { name: DEMAND_AREA, budgetPercent: 40, floorHours: 0 },
  ]);
  const { templateId } = await declareOneDayShape(client, "Everyday");

  const deadline = deadlineDate();
  for (const title of DEADLINE_TASKS) {
    await declareTask(client, {
      title,
      areaId: areas[DEMAND_AREA]!,
      estimateMinutes: EACH_MINUTES,
      deadline,
      minChunkMinutes: CHUNK_MINUTES,
      priority: "urgent",
    });
  }

  console.log(
    `owes_more_than_a_week: ${DEMAND_MINUTES} ${DEMAND_AREA} minutes due ${deadline} in ` +
      `${DEADLINE_TASKS.length} tasks of ${EACH_MINUTES}, against a week with no frame and no slot, ` +
      `so template ${templateId} materializes a plan holding nothing`,
  );
};
