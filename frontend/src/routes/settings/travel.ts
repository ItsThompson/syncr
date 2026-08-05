/* Which travel override covers a date, read from the overrides rather than inferred from the zone.
 *
 * THE ZONE IS A PROXY AND IT IS WRONG FOR ONE REAL CASE. The obvious reading of "am I travelling" is
 * `activeZone !== homeZone`, and it agrees with the overrides almost always. It disagrees when an override names
 * the home zone: the api refuses an OVERLAPPING pair and refuses an unknown zone, and it refuses neither a range
 * whose zone is the one already in force. Such a range is a real declaration, and a panel deriving coverage from
 * the zone states that no override covers today while one does.
 *
 * BOTH DATES ARE INCLUSIVE, which is the api's own contract, and an ISO date compares correctly as text because
 * its fields run longest-first and are zero-padded. So the comparison needs no parsing and no zone: a date is
 * already resolved in the zone it was resolved for.
 *
 * IT ANSWERS WITH THE OVERRIDE, NOT A BOOLEAN. A panel that has the range can name it, and a caller that only
 * needs the boolean reads it as a null check. Answering with the truth rather than a summary of it is what lets
 * the sentence get longer without this function changing. */

import type { TravelOverride } from "../../api/hooks/useSettings";

/**
 * The override covering a local date, or null when none does.
 *
 * The first match is the answer, which is unambiguous rather than arbitrary: the api refuses two overrides that
 * cover a common date, so at most one can match.
 */
export function overrideCovering(
  overrides: readonly TravelOverride[],
  date: string,
): TravelOverride | null {
  if (date === "") return null;
  return (
    overrides.find((override) => override.startDate <= date && date <= override.endDate) ?? null
  );
}
