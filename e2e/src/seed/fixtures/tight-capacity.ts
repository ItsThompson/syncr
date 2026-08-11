/* `tight_capacity`: a week whose declared floors sit just inside its remaining capacity, and whose
 * one deadline owes more before it than the week can hold in front of it.
 *
 * THE FIXTURE THREE OBSERVATIONS SHARE. `reference_week`'s plan week holds 5565 minutes of
 * discretionary time against 480 minutes of declared floor, so a floor reservation that nets nothing
 * still fits there: the B1 assertions have nothing to discriminate on a week that roomy, and they were
 * measured green under a bite that reverted the netting rule. S25 needs the same tightness from the
 * other direction, a week where pinning two hours of unrelated work moves a shortfall. And a verdict
 * that one mutation can flip is what makes a session-attributed infeasibility episode constructible at
 * all.
 *
 * HOW THE WEEK IS MADE TIGHT: by the FRAME, not by an oversized demand. Two routines cover twenty and a
 * half hours of every day, so three and a half hours a day are discretionary, and the Area slots
 * declared in them are what the floors are met by. That is the shape B1 is about: a healthy solved week
 * is one whose floors are met by UNPINNED solver-placed blocks.
 *
 * HOW THE DEADLINE IS MADE UNMEETABLE: by the CAPACITY IN FRONT OF IT, for the same reason. The
 * deadline task is one minimum chunk larger than the discretionary time that precedes its own deadline,
 * so the week reports a gap of exactly that chunk before anything is solved and before anything is
 * pinned, and it is a gap a pin moves in either direction: pinning the task's own work leaves both
 * sides of the comparison net of it, and pinning another Area's work into the same window takes from
 * one side only.
 *
 * A DEADLINE IS DECLARED AS A DATE AND READ AS THE INSTANT ITS MIDNIGHT FALLS AT, and midnight is
 * inside the sleep span at either offset, so the capacity in front of a deadline is a whole number of
 * discretionary days in summer and in winter both.
 *
 * The arithmetic is stated here and asserted by the scenarios rather than restated by them. Every
 * figure below is derived from the declarations underneath it rather than written beside them:
 *
 *   frame per day        Sleep 22:00 + 9h, Work 09:00 + 11h30m               20h30m
 *   discretionary        3h30m a day, seven days                       1470 minutes
 *   slots declared       Career 07:00 + 90m, Fitness 20:30 + 90m       1260 minutes
 *   floors declared      Career 8h, Fitness 8h                          960 minutes
 *   before the deadline  Monday and Tuesday, whole discretionary days   420 minutes
 *   the deadline's task  420 plus one 90-minute chunk                   510 minutes
 *   the gap it reports   510 against 420, before any solve or pin        90 minutes
 *
 * So the correct floor reservation is zero once the week is solved, because every floor minute is
 * already placed, and zero fits in whatever the solve leaves. A reservation that netted immovable
 * placements only would be 960 against that remainder, which is smaller than the floors themselves,
 * and would report a floor shortfall on a week that is fully scheduled, which is the defect B1 names.
 */

import type { ApiClient } from "../../api/client.ts";
import { dateIn, MONDAY, utcMidnightOn, WEDNESDAY } from "../../api/weeks.ts";
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

const floorMinutesOf = (name: string): number =>
  AREAS.find((area) => area.name === name)!.floorHours * 60;

export const CAREER_FLOOR_MINUTES = floorMinutesOf("Career");
export const FITNESS_FLOOR_MINUTES = floorMinutesOf("Fitness");
export const DEADLINE_TASK = "Lab report";

/* The frame, as two durations rather than as two numbers repeated in a comment. What the week has left
 * over follows from them, and so does everything the deadline is sized against, so a change to the
 * frame moves the fixture's whole arithmetic with it instead of leaving a stale figure behind. */
const SLEEP_MINUTES = 9 * 60;
const WORK_MINUTES = 11 * 60 + 30;
const DISCRETIONARY_MINUTES_A_DAY = 24 * 60 - SLEEP_MINUTES - WORK_MINUTES;

/** The week's denominator: what the frame leaves, over seven days. */
export const DISCRETIONARY_MINUTES = 7 * DISCRETIONARY_MINUTES_A_DAY;

/** The deadline task's own minimum chunk, which is the smallest placement that can close its gap. */
const CHUNK_MINUTES = 90;

/* The slots, as the list the seed iterates rather than as calls beside a count. What the week declares
 * follows from the list, so a slot added to it moves the figure the scenarios pin instead of leaving a
 * second number for a reader to keep in step by hand. */
const SLOT_MINUTES = 90;
const SLOTS = [
  { area: "Career", targetTime: "07:00:00" },
  { area: "Fitness", targetTime: "20:30:00" },
] as const;

/** The Area slot time the week declares: what the floors are met through. */
export const SLOT_MINUTES_A_WEEK = 7 * SLOTS.length * SLOT_MINUTES;

/** Which day of the plan week the deadline falls on, mid-week so that days precede it and follow it. */
const DEADLINE_WEEKDAY = WEDNESDAY;

/** The discretionary time in front of the deadline: the whole days between Monday and that midnight. */
export const PRE_DEADLINE_MINUTES = (DEADLINE_WEEKDAY - MONDAY) * DISCRETIONARY_MINUTES_A_DAY;

/** One chunk more than fits, so the week owes more before that instant than it can hold. */
export const DEADLINE_TASK_MINUTES = PRE_DEADLINE_MINUTES + CHUNK_MINUTES;

/** The gap the week therefore reports, before anything is solved and before anything is pinned. */
export const PRE_DEADLINE_SHORTFALL_MINUTES = DEADLINE_TASK_MINUTES - PRE_DEADLINE_MINUTES;

export const seedTightCapacity = async (client: ApiClient): Promise<void> => {
  await declareSettings(client);
  const areas = await declareAreas(client, AREAS);
  const { templateId } = await declareOneDayShape(client, "Everyday");

  // The frame. Nine hours of sleep and eleven and a half of committed work, which between them leave
  // 07:00 to 09:00 and 20:30 to 22:00 discretionary on every date.
  await declareRoutine(client, templateId, {
    title: "Sleep",
    targetTime: "22:00:00",
    durationMinutes: SLEEP_MINUTES,
  });
  await declareRoutine(client, templateId, {
    title: "Work",
    targetTime: "09:00:00",
    durationMinutes: WORK_MINUTES,
  });

  // The slots the floors are met through, one per discretionary window.
  for (const slot of SLOTS) {
    await declareSlot(client, templateId, {
      areaId: areas[slot.area]!,
      targetTime: slot.targetTime,
      durationMinutes: SLOT_MINUTES,
    });
  }

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
  // The deadline the week cannot meet, sized one minimum chunk past the discretionary time in front of
  // it. High priority and splittable in chunks, so a solve places what fits before the deadline there
  // rather than refusing the task whole: the gap that survives a solve is then capacity the week does
  // not have rather than a placement it declined to make.
  await declareTask(client, {
    title: DEADLINE_TASK,
    areaId: areas.Career!,
    estimateMinutes: DEADLINE_TASK_MINUTES,
    minChunkMinutes: CHUNK_MINUTES,
    deadline: utcMidnightOn(dateIn(planWeek(), DEADLINE_WEEKDAY)),
    priority: "high",
  });

  console.log(
    `tight_capacity: ${DISCRETIONARY_MINUTES} discretionary minutes a week against floors of ` +
      `${CAREER_FLOOR_MINUTES} and ${FITNESS_FLOOR_MINUTES}, and ${DEADLINE_TASK_MINUTES} minutes ` +
      `due against the ${PRE_DEADLINE_MINUTES} in front of the deadline`,
  );
};
