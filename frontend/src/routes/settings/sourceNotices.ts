/* The panel notices this screen raises about a source, and the banner the shell raises with them.
 *
 * TWO CONDITIONS ARE COMPOSED HERE AND ONE IS NOT. Write-target expiry and a stopped projection are composed by
 * the api, on `GET /calendar-sources/google/connection`, so their words are written once and the banner and the
 * panel cannot state the outage differently. A feed that cannot be read has no server-composed notice, so this
 * module composes it from the sync state the source already carries.
 *
 * `stillWorks` IS NEVER EMPTY, and the kit's type is what enforces it: a notice that says only what broke leaves
 * a reader unable to decide what to do next. Every notice below names what survives, because for both feed
 * conditions a great deal does: the anchors already read are retained, the week still solves, and the plan still
 * reaches the calendar.
 *
 * THE STALENESS THRESHOLD IS THIS SCREEN'S, AND THAT IS A GAP RATHER THAN A CHOICE. `19-nonfunctional.md`
 * requires a panel here and an inline notice on the affected days once a feed has been unreachable for "longer
 * than a stated threshold", and nothing on the wire states one. Twelve hours is stated here so the panel can
 * name it. Two surfaces need the same figure, so the wire is where it belongs: ticket 1480 carries moving it,
 * and until then the grid's inline notice must read this constant rather than pick its own. */

import { type Notice } from "../../ui/domain";
import type { CalendarSource } from "../../api/hooks/useCalendarSources";

/**
 * How long a feed may fail before its panel is raised, in hours.
 *
 * Long enough that one missed poll of an hourly feed is not a notice, short enough that a reader planning
 * tomorrow morning is told today. A feed that has NEVER succeeded raises the panel on its first failure
 * regardless, because there is no last success to be within the threshold of.
 */
export const STALE_AFTER_HOURS = 12;

const MILLISECONDS_IN_HOUR = 60 * 60 * 1000;

const SETTINGS_SCREEN = "settings";

/** What survives a feed that cannot be read. Both are true and both matter to the next decision. */
const FEED_STILL_WORKS: readonly [string, ...string[]] = [
  "The anchors this feed already contributed, which are retained and marked possibly stale",
  "Solving the week, and writing the plan to your calendar",
];

/** True when a source's last attempt failed and the last success is older than the threshold. */
export function isFeedStale(source: CalendarSource, now: number): boolean {
  const { lastError, lastSuccessAt } = source.syncState;
  if (lastError === null || lastError === undefined) return false;
  if (lastSuccessAt === null || lastSuccessAt === undefined) return true;
  const succeeded = Date.parse(lastSuccessAt);
  if (Number.isNaN(succeeded)) return true;
  return now - succeeded > STALE_AFTER_HOURS * MILLISECONDS_IN_HOUR;
}

/**
 * The amber panel a source that cannot be read raises, or null while it can be read.
 *
 * The detail states WHEN it last succeeded rather than how long ago, because the notice carries `since` and the
 * panel renders the age from it: saying both would be the same fact twice in one paragraph.
 */
export function staleFeedNotice(source: CalendarSource, now: number): Notice | null {
  if (!isFeedStale(source, now)) return null;
  const succeeded = source.syncState.lastSuccessAt ?? null;
  return {
    id: `calendar.feed-stale.${source.id}`,
    volume: "panel",
    pigment: "amber",
    title: `${source.displayName} could not be read`,
    detail:
      `${source.syncState.lastError ?? "The last attempt failed."} ` +
      (succeeded === null
        ? "This feed has never been read successfully, so it has contributed no anchors yet."
        : "The anchors it already contributed are retained and marked possibly stale rather than " +
          "removed, so nothing disappears from a week you have already planned.") +
      ` A feed is reported here once it has been failing for more than ${STALE_AFTER_HOURS} hours.`,
    unavailable: [`Reading new commitments from ${source.displayName}`],
    stillWorks: FEED_STILL_WORKS,
    since: succeeded,
    action: null,
    scope: { screen: SETTINGS_SCREEN, sourceId: source.id },
  };
}

/**
 * The amber panel a feed with rejected components raises, stating the count and the reason per class.
 *
 * A rejection is not a failure of the feed: the rest of it was read. What the panel adds is that some of it was
 * not, and which kind of thing was refused, because "three events were rejected" without a class is a number a
 * reader can do nothing with.
 */
export function rejectionNotice(source: CalendarSource): Notice | null {
  const { rejectedCount, rejections } = source.syncState;
  if (rejectedCount === 0) return null;
  return {
    id: `calendar.feed-rejections.${source.id}`,
    volume: "panel",
    pigment: "amber",
    title: `${rejectedCount} event${rejectedCount === 1 ? "" : "s"} in ${source.displayName} could not be read`,
    detail:
      `${countByClass(rejections)}. Every other event in the feed was read, so the anchors from it are ` +
      "complete apart from these. A rejection names the line it began on, so the feed's owner can be told " +
      "exactly what to correct.",
    unavailable: [
      `${rejectedCount} event${rejectedCount === 1 ? "" : "s"} from ${source.displayName}`,
    ],
    stillWorks: FEED_STILL_WORKS,
    since: source.syncState.lastSuccessAt ?? null,
    action: null,
    scope: { screen: SETTINGS_SCREEN, sourceId: source.id },
  };
}

/** `2 unknown-zone, 1 missing-duration`, in the order the classes first appear. */
function countByClass(rejections: CalendarSource["syncState"]["rejections"]): string {
  const counts = new Map<string, number>();
  for (const rejection of rejections) {
    counts.set(rejection.kind, (counts.get(rejection.kind) ?? 0) + 1);
  }
  if (counts.size === 0) return "The feed did not say which components it refused";
  return [...counts].map(([kind, count]) => `${count} ${kind}`).join(", ");
}

/** Every panel this screen raises about its sources, in source order. */
export function sourcePanelNotices(
  sources: readonly CalendarSource[],
  now: number,
): readonly Notice[] {
  return sources.flatMap((source) => {
    if (!source.included) return [];
    const raised = [staleFeedNotice(source, now), rejectionNotice(source)];
    return raised.filter((notice): notice is Notice => notice !== null);
  });
}
