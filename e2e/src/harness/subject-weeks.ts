/* Which weeks a scenario drives, and why it is those.
 *
 * Every one is derived from today, because the maintainer plans `[today, today + horizon_days)` and a
 * week named as a literal leaves that window. What each name means is a decision the whole suite
 * shares, so it is made once here rather than per scenario.
 */

import { civilDateIn, isoWeekOf, isoWeekShift, type IsoWeekId } from "../api/weeks.ts";
import { HOME_ZONE } from "../config.ts";

/** The ISO week today falls in, read in the tenant's home zone. Holds days already lived. */
export const currentWeek = (): IsoWeekId => isoWeekOf(civilDateIn(HOME_ZONE));

/** The week most scenarios drive: NEXT week.
 *
 * Two properties no other week has at once. Every one of its days is in the future, whatever weekday
 * the suite runs on, so a deadline placed in it is never already passed and a block in it is never
 * already ended. And its Sunday is at most thirteen days out, so a 14-day horizon always covers the
 * whole of it: the maintainer materializes it without the horizon having to be widened.
 *
 * A scenario about the past (a backfill, a skipped block, a deadline the clock has passed) uses
 * `currentWeek` instead, and says so. */
export const planWeek = (): IsoWeekId => isoWeekShift(currentWeek(), 1);

/** A week fifty weeks out: far enough that no horizon setting reaches it, which is S1's second half. */
export const beyondHorizonWeek = (): IsoWeekId => isoWeekShift(currentWeek(), 50);
