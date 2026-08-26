/* `repeated_pins`: the reference week, plus one content pinned to one local time across three
 * consecutive weeks, which is what raises a promotion candidate into a weekly session.
 *
 * WHY THE PINS SIT BEYOND THE PLAN WEEK. A promotion is three consecutive ISO weeks of pins on one
 * content at one weekday and minute of the home-zone day (`CONSECUTIVE_WEEKS_FOR_PROMOTION`), and a
 * pin is refused on a block that has already begun. The horizon plans fourteen days ahead, so no
 * fixture can pin three FUTURE weeks through materialization alone: which weeks that reaches depends
 * on the weekday the suite runs on. These weeks are brought in by solving them explicitly instead --
 * `POST /weeks/{week}/solve` takes any week, and the scenario table's own beyond-horizon statement
 * offers "solve this week now" as the product's way to do it -- so every pinned block is days beyond
 * the horizon and none has begun whenever the suite runs.
 *
 * WHAT IS PINNED, AND WHY THE MOVE IS REAL. Wednesday's `Dinner` block, from its declared 19:00 to
 * 19:15, in each of three weeks. The target instant is computed as a WALL time in the home zone for
 * each week's own date, so the three pins group under one candidate even across a daylight-saving
 * boundary: the rule groups on the local minute of the day, not on the UTC offset.
 *
 * WHERE THE SESSION READS THEM. The session reviews the thirteen weeks before its own, so the case
 * that reads the promotion panel opens the session four weeks after the plan week: its window ends
 * one week past the last pin, and holds all three of them. That session week is solved too, so the
 * screen renders an ordinary weekly session over a live plan rather than an empty-week state.
 */

import type { ApiClient } from "../../api/client.ts";
import { stated } from "../../api/client.ts";
import type { IsoWeekId } from "../../api/weeks.ts";
import { dateIn, instantAt, isoWeekShift, WEDNESDAY } from "../../api/weeks.ts";
import { HOME_ZONE } from "../../config.ts";
import { planWeek } from "../../harness/subject-weeks.ts";
import { until, weekView } from "../../harness/week.ts";
import { seedReferenceWeek } from "./reference-week.ts";

/** The content the fixture pins, as the week view names the block drawn from the routine. */
export const PINNED_TITLE = "Dinner";

/** The routine's declared wall time, and where three weeks of pins move it to. */
const DINNER_WALL_TIME = "19:00:00";
export const PINNED_WALL_TIME = "19:15:00";

/** How far past the plan week the pinned weeks sit, and how far past them the session sits. */
const PIN_OFFSETS = [1, 2, 3] as const;

/** The week whose session reviews all three pinned weeks, as the case that renders the panel reads. */
export const promotionSessionWeek = (): IsoWeekId => isoWeekShift(planWeek(), 4);
/** Solve `week` now and wait until the solver has PLACED something, whichever operation carried it.
 *
 * The state waited for is solver-placed content rather than one operation's status: a solve answered
 * while a sibling is due may end `superseded` without the week being any less solved. Merely READING
 * the week assembles a plan of frames alone, which is why the marker is an origin the assembler
 * never draws -- the same marker `b1-s34-floors-and-unallocated.spec.ts` reads. */
const solveToPlan = async (client: ApiClient, week: IsoWeekId): Promise<void> => {
  const reply = await client.attempt("POST", `/api/v1/weeks/${week}/solve?immediate=true`);
  if (reply.status >= 400) {
    throw new Error(stated("POST", `/api/v1/weeks/${week}/solve`, reply));
  }
  await until(
    `${week} to hold solver-placed blocks`,
    () => weekView(client, week),
    (seen) => seen.live?.blocks.some((block) => block.origin !== "frame") ?? false,
  );
};

export const seedRepeatedPins = async (client: ApiClient): Promise<void> => {
  await seedReferenceWeek(client);

  // The plan week is SOLVED, not left to materialization alone. A week the maintainer planned but
  // nobody asked to solve holds frame blocks only, and the session then raises nothing at all --
  // which reddens the raised-panel assertion below it through no fault of its own. Solving places
  // the habit occurrences the cadence items count, so the week always has something raised.
  const pinnedWeeks = PIN_OFFSETS.map((offset) => isoWeekShift(planWeek(), offset));
  const session = promotionSessionWeek();
  for (const week of [planWeek(), ...pinnedWeeks, session]) await solveToPlan(client, week);

  // One pin per week, each moving Wednesday's Dinner a quarter hour later than the plan drew it,
  // at the same wall time every week. A pin that moved nothing would be dropped by the rule.
  let pinned = 0;
  for (const week of pinnedWeeks) {
    const wednesday = dateIn(week, WEDNESDAY);
    const declaredStart = Date.parse(instantAt(wednesday, DINNER_WALL_TIME, HOME_ZONE));
    const view = await weekView(client, week);
    const dinner = view.live?.blocks.find(
      (block) => block.title === PINNED_TITLE && Date.parse(block.interval.start) === declaredStart,
    );
    if (!dinner) {
      throw new Error(`${week} holds no ${PINNED_TITLE} at ${DINNER_WALL_TIME} on ${wednesday}`);
    }
    const reply = await client.attempt("POST", `/api/v1/weeks/${week}/pins`, {
      blockId: dinner.id,
      start: instantAt(wednesday, PINNED_WALL_TIME, HOME_ZONE),
    });
    if (reply.status !== 201) {
      throw new Error(stated("POST", `/api/v1/weeks/${week}/pins`, reply));
    }
    pinned += 1;
  }

  console.log(
    `repeated_pins: ${PINNED_TITLE} pinned to ${PINNED_WALL_TIME} on Wednesday in ` +
      `${pinned} weeks (${pinnedWeeks.join(", ")}); the panel reads the session of ${session}`,
  );
};
