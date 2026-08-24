/* The four notices this screen raises, each at the volume and pigment the shell's table assigns it.
 *
 * VOLUME IS POSITION AND PIGMENT IS KIND, so both are decided here rather than at the element:
 *
 *   a day nobody has answered for   inline on the day, INFORMATIONAL. Nothing is broken and nothing
 *                                   needs attention: an unconfirmed day is the ordinary state of a day
 *                                   until the evening pass, and amber would teach a reader to distrust it
 *   a refused recording             inline on the ROW, amber. The api applied nothing, the row still reads
 *                                   as it did, and the repair is the control the reader already has open
 *   a refused confirmation          inline on the day, amber, for the same reasons one row up
 *   a backfill that settled days    inline on the day, verdigris, which is the one pigment for a
 *                                   confirmation and is spent sparingly
 *
 * EVERY NOTICE NAMES WHAT STILL WORKS, which the kit's type refuses to let a caller leave empty. A refusal
 * that says only what failed leaves a reader unable to decide what to do next, and on this screen the
 * answer is always the same shape: the rest of the ledger is unaffected and the act can be repeated.
 *
 * A FEED THAT CANNOT BE READ IS NOT COMPOSED HERE. The api composes that notice -- threshold, words, days in
 * doubt -- and sends it on the source list; this screen only renders the ones whose scope names THIS day. */

import { noticeFrom, type Notice, type WireNotice } from "../../ui/domain";
import type { Problem } from "../../contract";

/** The api's own sentence, with the members it named first: a 422 says which figure to change. */
function detailOf(problem: Problem): string {
  const members = (problem.errors ?? []).map((error) => `${error.field} ${error.message}.`);
  return [...members, problem.detail].join(" ");
}

/** A day nobody has answered for yet, stated at informational volume beside its own controls. */
export function unconfirmedNotice(date: string, unconfirmedDays: number): Notice {
  const others =
    unconfirmedDays === 0
      ? "No earlier day is outstanding."
      : `${unconfirmedDays} earlier ${unconfirmedDays === 1 ? "day is" : "days are"} outstanding too.`;
  return {
    id: `day-unconfirmed-${date}`,
    volume: "inline",
    pigment: "info",
    title: "This day is not confirmed",
    detail: `Nothing has been answered for yet, so this day is excluded from reviews and from learning. ${others}`,
    unavailable: [],
    stillWorks: ["confirming it now", "confirming it on any later day"],
    since: null,
    action: null,
    scope: { screen: "today", date },
  };
}

/** A recording the api refused, beside the row it was refused on. */
export function recordingRefusedNotice(blockId: string, problem: Problem): Notice {
  return {
    id: `outcome-refused-${blockId}`,
    volume: "inline",
    pigment: "amber",
    title: problem.title,
    detail: detailOf(problem),
    unavailable: [],
    stillWorks: ["this row, which still reads as it did", "recording it again"],
    since: null,
    action: null,
    scope: { screen: "today", blockId },
  };
}

/** A confirmation the api refused, beside the day's own controls. */
export function confirmationRefusedNotice(date: string, problem: Problem): Notice {
  return {
    id: `confirm-refused-${date}`,
    volume: "inline",
    pigment: "amber",
    title: problem.title,
    detail: detailOf(problem),
    unavailable: [],
    stillWorks: ["the ledger, which still reads as it did", "confirming the day again"],
    since: null,
    action: null,
    scope: { screen: "today", date },
  };
}

/** What a backfill settled, which is the response's own figures rather than the count that offered it. */
export function backfillSettledNotice(date: string, reading: string, outstanding: number): Notice {
  return {
    id: `backfill-settled-${date}`,
    volume: "inline",
    pigment: "verdigris",
    title: "Past days confirmed",
    detail: `${reading} ${outstanding} past ${outstanding === 1 ? "day is" : "days are"} still outstanding.`,
    unavailable: [],
    stillWorks: ["correcting any of them by naming the day"],
    since: null,
    action: null,
    scope: { screen: "today", date },
  };
}

/**
 * The api's own notices that put THIS day in doubt, narrowed to the kit's type.
 *
 * Whether a feed is stale, and which days its outage touches, are decided where the anchors live, on the api:
 * the notice carries those days in its scope, so rendering one on the day it names is a filter rather than a
 * computation. A notice whose list cannot be narrowed is dropped, as `noticesAt` drops it everywhere else.
 */
export function noticesOnDate(wire: readonly WireNotice[], date: string): readonly Notice[] {
  return wire.flatMap((notice) => {
    if (!notice.scope?.dates?.includes(date)) return [];
    const narrowed = noticeFrom(notice);
    return narrowed === null ? [] : [narrowed];
  });
}
