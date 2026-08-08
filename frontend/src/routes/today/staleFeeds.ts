/* THE FEED THIS DAY DEPENDS ON, AND WHETHER IT CAN STILL BE READ.
 *
 * A stale feed raises a panel on Settings, which is where a source is managed. That is not enough on its own: a
 * reader planning their evening is looking at a day, and the commitments on that day came from a feed that may
 * have stopped answering hours ago. The anchors are RETAINED and marked possibly stale rather than removed,
 * because a failed sync is not evidence that a commitment was cancelled -- so the day looks exactly as it did
 * when the feed was healthy. A degraded state that renders identically to a working one is the failure this
 * notice exists to close.
 *
 * ONLY A DAY THAT HOLDS AN IMPORTED COMMITMENT IS AFFECTED. A day whose every row is a task or a routine owes
 * nothing to any feed, and a notice there would be noise on a day the outage cannot have touched. So the
 * condition is read from the day's own rows rather than from the fact that a source somewhere is failing.
 *
 * THE THRESHOLD IS THE ONE SETTINGS USES. `isFeedStale` and `STALE_AFTER_HOURS` are imported rather than
 * restated: two surfaces reporting one condition at two thresholds would disagree about whether a feed is
 * stale, and the panel names the figure in its own sentence. Ticket 1480 carries moving that figure to the
 * wire, where both surfaces would read it instead. */

import { isFeedStale, STALE_AFTER_HOURS } from "../settings/sourceNotices";
import type { CalendarSource } from "../../api/hooks/useCalendarSources";
import type { Day } from "../../api/hooks/useDay";
import type { Notice } from "../../ui/domain";

const ANCHOR: Day["ahead"][number]["origin"] = "anchor";

/** What survives a feed that cannot be read, on a day that holds its commitments. */
const STILL_WORKS: readonly [string, ...string[]] = [
  "every commitment already read from it, which is still on this day",
  "recording outcomes and confirming the day",
];

/** True when any row of this day came from an imported commitment. */
function holdsAnImportedCommitment(day: Day): boolean {
  return [...day.behind, ...day.ahead].some((row) => row.origin === ANCHOR);
}

/**
 * The inline notice each unreadable feed raises on this day, or none.
 *
 * Amber, because nothing is broken: the day is complete as far as syncr knew, and what has stopped is learning
 * about changes to it. Inline, because it is about this day rather than about the product, and the panel that is
 * about the source is on Settings.
 */
export function staleFeedNotices(
  day: Day,
  sources: readonly CalendarSource[],
  now: number,
): readonly Notice[] {
  if (!holdsAnImportedCommitment(day)) return [];
  return sources
    .filter((source) => source.included && isFeedStale(source, now))
    .map((source) => ({
      id: `feed-stale-${source.id}-${day.date}`,
      volume: "inline" as const,
      pigment: "amber" as const,
      title: `${source.displayName} may be out of date`,
      detail: `${lastRead(source)} The commitments it contributed are still on this day, marked possibly stale rather than removed, so nothing has disappeared from a day you have already planned. A feed is reported once it has been failing for more than ${String(STALE_AFTER_HOURS)} hours.`,
      unavailable: [`changes made to ${source.displayName} since then`],
      stillWorks: STILL_WORKS,
      since: source.syncState.lastSuccessAt ?? null,
      action: null,
      scope: { screen: "today", date: day.date, sourceId: source.id },
    }));
}

/** When the feed last answered, or that it never has. */
function lastRead(source: CalendarSource): string {
  return source.syncState.lastSuccessAt === null || source.syncState.lastSuccessAt === undefined
    ? "This feed has never been read successfully."
    : "syncr has not been able to read this feed since it last succeeded.";
}
