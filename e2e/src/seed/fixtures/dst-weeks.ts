/* `dst_weeks`: the spring-forward week and the fall-back week, in a real zone, each with a
 * Sunday-night frame span crossing the ISO week boundary.
 *
 * WHAT THIS FIXTURE CAN AND CANNOT REACH, stated because the difference decides what a scenario may
 * claim. The declarations are complete: a real zone, a Sleep routine at 23:00 for eight hours on
 * every date, so every Sunday night's frame crosses into Monday, and a travel override across a
 * transition. What it cannot do is put a plan in those weeks unless the horizon reaches them: the
 * maintainer plans `[today, today + horizon_days)` and `horizon_days` is capped at 90, so at most one
 * of the two transitions is ever inside it and usually neither is.
 *
 * So this fixture prints the two week identifiers and the transition dates it computed, which is the
 * seeded precondition S18 is observed against by hand. It does not pretend to have materialized a
 * week it could not.
 */

import type { ApiClient } from "../../api/client.ts";
import { civilDateIn, dateShift, isoWeekOf } from "../../api/weeks.ts";
import { HOME_ZONE } from "../../config.ts";
import { domainConstants } from "../../harness/compose.ts";
import { declareBaseline } from "../baseline.ts";
import { declareRoutine } from "../declarations.ts";

/* The zone offset in minutes at midday on `date`, which is what a transition changes. Midday rather
 * than midnight so no reading falls inside the gap a spring-forward opens. */
const offsetMinutesAt = (date: string, zone: string): number => {
  const noonUtc = new Date(`${date}T12:00:00Z`);
  const zoned = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(noonUtc);
  const read = (type: string): string => zoned.find((part) => part.type === type)?.value ?? "00";
  const asUtc = new Date(
    `${read("year")}-${read("month")}-${read("day")}T${read("hour")}:${read("minute")}:00Z`,
  );
  return (asUtc.getTime() - noonUtc.getTime()) / 60_000;
};

/** Every date within `days` of `from` whose offset differs from the day before it. */
export const transitionsAfter = (from: string, zone: string, days: number): readonly string[] => {
  const found: string[] = [];
  let previous = offsetMinutesAt(from, zone);
  for (let day = 1; day <= days; day += 1) {
    const date = dateShift(from, day);
    const offset = offsetMinutesAt(date, zone);
    if (offset !== previous) found.push(date);
    previous = offset;
  }
  return found;
};

/* A year and a day, so both of a zone's two transitions are always found whatever the date today
 * is. Which of them the horizon can reach is a separate question this fixture does not decide. */
const A_YEAR = 366;

export const seedDstWeeks = async (client: ApiClient): Promise<void> => {
  const stated = (await domainConstants()).dst_weeks;
  const { areas, templateId } = await declareBaseline(client);

  // The frame that crosses the boundary. Every Sunday's sleep runs into Monday, which is what makes a
  // week's first block one it inherited. The target and the duration are the domain fixture's.
  await declareRoutine(client, templateId, {
    title: "Sleep",
    targetTime: stated.sleepTargetTime,
    durationMinutes: stated.sleepDurationMinutes,
  });
  await declareRoutine(client, templateId, {
    title: "Wake Up",
    targetTime: "07:00:00",
    durationMinutes: 15,
  });

  const today = civilDateIn(HOME_ZONE);
  const transitions = transitionsAfter(today, stated.zone, A_YEAR);
  const weeks = transitions.map((date) => `${isoWeekOf(date)} (transition on ${date})`);

  // A travel override across the NEXT transition, so the zone the frame is read in changes inside a
  // week that also changes offset: the two effects are separable only when both are present.
  const nextTransition = transitions[0];
  if (nextTransition) {
    await client.post("/api/v1/settings/travel-overrides", {
      startDate: dateShift(nextTransition, -2),
      endDate: dateShift(nextTransition, 2),
      zone: "Pacific/Auckland",
    });
  }

  console.log(`dst_weeks: ${stated.zone} transitions at ${weeks.join(" and ")}`);
  console.log(`dst_weeks: Areas are ${Object.keys(areas).join(", ")}`);
};
