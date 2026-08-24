/* The panel notices this screen composes about a source, and the banner the shell raises with them.
 *
 * ONE CONDITION IS COMPOSED HERE. Write-target expiry, a stopped projection and a feed that can no longer be read
 * are composed by the api -- the stale-feed panel arrives on the source list itself -- so their words are written
 * once and no two surfaces can state the same outage differently. What is left here is the parse rejection: the
 * count and the reason per class, stated from the sync state the source already carries.
 *
 * `stillWorks` IS NEVER EMPTY, and the kit's type is what enforces it: a notice that says only what broke leaves
 * a reader unable to decide what to do next. Every notice below names what survives, because for a rejected read
 * a great deal does: the anchors already read are retained, the week still solves, and the plan still reaches the
 * calendar. */

import { type Notice } from "../../ui/domain";
import type { CalendarSource } from "../../api/hooks/useCalendarSources";

const SETTINGS_SCREEN = "settings";

/** What survives a read whose feed answered but refused some of what it holds. */
const FEED_STILL_WORKS: readonly [string, ...string[]] = [
  "The anchors this feed already contributed, which are retained and marked possibly stale",
  "Solving the week, and writing the plan to your calendar",
];

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
      `${countByClass(rejections)}${sampleSentence(rejections.length, rejectedCount)}. Every other event in the feed was read, so the anchors from it are ` +
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

/* The wire's rejection list is a bounded sample and its count is not, so the per-class figures above are
 * what was SHOWN rather than what happened. The sentence names both, so a reader never mistakes the list
 * for the whole refusal. Where the api reported a count with no rows behind it there is nothing shown to
 * bound, and `countByClass` already says the classes are unknown. */
function sampleSentence(sampled: number, total: number): string {
  if (sampled === 0) return "";
  if (total > sampled) return `; showing the first ${sampled} of ${total}`;
  return ", all of which are shown";
}

/**
 * Every rejection panel this screen composes, in source order.
 *
 * An excluded source contributes nothing because the reader asked it to, so its rejections raise nothing either:
 * the panel exists to explain anchors that are missing, and an excluded source promises none.
 */
export function rejectionPanels(sources: readonly CalendarSource[]): readonly Notice[] {
  return sources.flatMap((source) => {
    if (!source.included) return [];
    const raised = [rejectionNotice(source)];
    return raised.filter((notice): notice is Notice => notice !== null);
  });
}
