/* `reference_week`: the one week every other question is asked about.
 *
 * The same shapes the solver's own `reference_week` holds, declared through the API instead of
 * through the solver's input types, so a rendering question and a solver question can be asked about
 * the same data. Every shape it declares:
 *
 * | Shape | Where |
 * |---|---|
 * | a frame span crossing midnight | `Sleep`, 23:00 for eight hours, on every date |
 * | a fifteen-minute compact block | `Wake Up`, 07:00 |
 * | an interview anchor with prep, transit and recovery | the `Interview` type over the geometry feed |
 * | an anchor conflict | Monday's 09:00 lecture over the 09:00 Career slot |
 * | a depth-3 overlap | Friday's two lectures inside the Friday night frame |
 * | a pinned habit | pinned by the scenario that needs one, so the seed stays one state |
 * | a queue binding | `Leetcode` draws from the Career backlog |
 * | 61 timed blocks | not a target: what the week HOLDS is what the assertions read |
 *
 * WHY THE WEEK IS DERIVED FROM TODAY. The solver's fixture names 2026-W07 because a unit test may
 * name any week. This one may not: the maintainer plans `[today, today + horizon_days)`, so a
 * literal week leaves the horizon and every scenario then reads an empty week.
 */

import type { ApiClient } from "../../api/client.ts";
import { dateIn, FRIDAY, THURSDAY, utcMidnightOn } from "../../api/weeks.ts";
import { ICS_PROVIDER } from "../../config.ts";
import { planWeek } from "../../harness/subject-weeks.ts";
import {
  declareAnchorType,
  declareAreas,
  declareHabit,
  declareIcsSource,
  declareOneDayShape,
  declareRoutine,
  declareSettings,
  declareSlot,
  declareTask,
} from "../declarations.ts";

/* Four Areas summing to 75%, deliberately not 100: S34 asserts that `Unallocated` is honest, and a
 * budget summing to 100 is the case it sets up for itself. */
const AREAS = [
  { name: "Career", budgetPercent: 30, floorHours: 3 },
  { name: "Fitness", budgetPercent: 20, floorHours: 5 },
  { name: "Study", budgetPercent: 20, floorHours: 0 },
  { name: "Transit", budgetPercent: 5, floorHours: 0 },
] as const;

export const seedReferenceWeek = async (client: ApiClient): Promise<void> => {
  await declareSettings(client);
  const areas = await declareAreas(client, AREAS);
  const { templateId } = await declareOneDayShape(client, "Everyday");

  // The frame. Sleep crosses midnight, so the week inherits a span from the one before it, which is
  // what makes the Monday-morning overhang a real case rather than a drawn one.
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
  await declareRoutine(client, templateId, {
    title: "Shower",
    targetTime: "07:15:00",
    durationMinutes: 15,
  });
  // 19:00 is where the seminar feed collides, so S12 has a planned block to conflict with.
  await declareRoutine(client, templateId, {
    title: "Dinner",
    targetTime: "19:00:00",
    durationMinutes: 60,
  });

  // Two slots. The Career one sits at 09:00, where Monday's lecture lands, which is the anchor
  // conflict the fixture table names.
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

  await declareHabit(client, {
    title: "Gym",
    areaId: areas.Fitness!,
    minDurationMinutes: 45,
    timesPerWeek: 3,
    bindingSource: "rotation",
    variants: ["Push", "Pull", "Legs"],
    missPolicy: "debt",
  });
  await declareHabit(client, {
    title: "Leetcode",
    areaId: areas.Career!,
    minDurationMinutes: 60,
    timesPerWeek: 2,
    bindingSource: "queue",
  });
  await declareHabit(client, {
    title: "Reading",
    areaId: areas.Study!,
    minDurationMinutes: 30,
    maxDurationMinutes: 90,
    timesPerWeek: 2,
  });

  // Deadlines land in the week every scenario drives, which is next week: a deadline on a weekday of
  // THIS week is already passed whenever the suite runs after Wednesday, and a passed deadline is
  // S36's subject rather than the reference week's.
  const subject = planWeek();
  await declareTask(client, {
    title: "F&F Past Papers",
    areaId: areas.Career!,
    estimateMinutes: 240,
    deadline: utcMidnightOn(dateIn(subject, FRIDAY)),
    minChunkMinutes: 45,
    priority: "high",
  });
  await declareTask(client, {
    title: "Write up the interview prep",
    areaId: areas.Career!,
    estimateMinutes: 120,
    deadline: utcMidnightOn(dateIn(subject, THURSDAY)),
    minChunkMinutes: 30,
  });
  await declareTask(client, {
    title: "Read the distributed systems chapter",
    areaId: areas.Study!,
    estimateMinutes: 90,
    minChunkMinutes: 30,
  });

  // The three anchor types, with the geometry `block-states.html` and `screens.html` render. The
  // Interview's numbers are S33's: prep 6h before, transit 60 minutes' lead over a 30-minute leg, no
  // return, and a 75-minute recovery forbidding Study only.
  await declareAnchorType(client, {
    name: "Interview",
    matchTitleContains: "Interview",
    prepAreaId: areas.Career!,
    prepLeadMinutes: 360,
    prepDurationMinutes: 30,
    transitAreaId: areas.Transit!,
    transitLeadMinutes: 60,
    transitDurationMinutes: 30,
    returnTransitMinutes: 0,
    postBufferMinutes: 75,
    postScope: "areas",
    forbiddenAreaIds: [areas.Study!],
  });
  // `Pre 0m` with a transit leg and a return leg: the case the prep-collision rule must ACCEPT.
  await declareAnchorType(client, {
    name: "Lecture",
    matchTitleContains: "Lecture",
    transitAreaId: areas.Transit!,
    transitLeadMinutes: 30,
    transitDurationMinutes: 30,
    returnTransitMinutes: 30,
  });

  // Synced BEFORE the week is materialized, so the anchors already exist when the plan is drawn
  // around them: that is one of the two sites a conflict is raised at, and the seminar feed is what
  // reaches it. The Wednesday seminar sits at 19:00, which is Dinner's target time, so materializing
  // the week draws a block under a commitment and the overlap is raised rather than resolved.
  await declareIcsSource(client, "University timetable", `${ICS_PROVIDER}/reference.ics`);
  await declareIcsSource(client, "Interviews and exams", `${ICS_PROVIDER}/geometry.ics`);
  await declareIcsSource(client, "Department seminars", `${ICS_PROVIDER}/conflict.ics`);
};
