/* Which past days one backfill settles.
 *
 * THE WINDOW IS THE ONE THE COUNT IS TAKEN OVER, and that is why the figure is repeated here rather than
 * inferred: the api counts the unconfirmed days of the last 28 and refuses a range wider than 28 with a
 * stated reason, so a control offering to settle "the outstanding days" has to name exactly that window. A
 * client asking for more would be asking to settle days the count it rendered could not have offered.
 *
 * TODAY IS NOT IN THE RANGE. A day the reader is still living is not one they have failed to answer for, and
 * this screen confirms it with its own control.
 *
 * A DRIFT IS VISIBLE RATHER THAN SILENT. If the api's window changes, this range either falls short by a day
 * or is refused with the api's own sentence naming both figures; neither reads as a backfill that worked. */

import { shiftDate } from "../../ui/primitives";
import type { BackfillRange } from "../../api/hooks/useDay";

/** How far back the count of unconfirmed days reads, which is the same figure the api bounds a range by. */
export const UNCONFIRMED_LOOKBACK_DAYS = 28;

/** The 28 days before this date, both ends included, which is what the count was taken over. */
export function backfillRange(date: string): BackfillRange {
  return {
    from: shiftDate(date, -UNCONFIRMED_LOOKBACK_DAYS) ?? date,
    to: shiftDate(date, -1) ?? date,
  };
}
