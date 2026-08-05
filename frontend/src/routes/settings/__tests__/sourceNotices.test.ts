/* The two feed panels this screen composes, and the field the kit's type will not let them omit.
 *
 * `stillWorks` IS THE CLAIM UNDER TEST here, not a detail. Every degradation notice in this product names the
 * capability that survives, and for a feed a great deal does: the anchors already read are retained and marked
 * possibly stale, and the week still solves and still reaches the calendar. A notice that said only what broke
 * would leave a reader unable to decide whether to plan around what they can see. */

import { describe, expect, it } from "vitest";

import {
  STALE_AFTER_HOURS,
  isFeedStale,
  rejectionNotice,
  sourcePanelNotices,
  staleFeedNotice,
} from "../sourceNotices";
import { NOW, SOURCE_PERSONAL, buildSource, buildSyncState } from "./fixtures";

const HOUR = 60 * 60 * 1000;

const failing = (hoursSinceSuccess: number | null) =>
  buildSource({
    state: "error",
    syncState: buildSyncState({
      lastError: "The feed answered 503 Service Unavailable.",
      lastAttemptAt: new Date(NOW - HOUR).toISOString(),
      lastSuccessAt:
        hoursSinceSuccess === null ? null : new Date(NOW - hoursSinceSuccess * HOUR).toISOString(),
    }),
  });

describe("whether a feed counts as stale", () => {
  it("is not stale while its last attempt succeeded", () => {
    expect(isFeedStale(buildSource(), NOW)).toBe(false);
  });

  it("is not stale while the failure is inside the threshold", () => {
    expect(isFeedStale(failing(STALE_AFTER_HOURS - 1), NOW)).toBe(false);
  });

  it("is stale once the last success is older than the threshold", () => {
    expect(isFeedStale(failing(STALE_AFTER_HOURS + 1), NOW)).toBe(true);
  });

  /* A feed that has never been read has no last success to be inside the threshold of, so its first failure is
   * reportable: there is nothing to wait for. */
  it("is stale on the first failure of a feed that has never been read", () => {
    expect(isFeedStale(failing(null), NOW)).toBe(true);
  });
});

describe("the panel a stale feed raises", () => {
  const notice = staleFeedNotice(failing(30), NOW);

  it("is amber at panel volume, because nothing is broken and the plan is unaffected", () => {
    expect(notice?.pigment).toBe("amber");
    expect(notice?.volume).toBe("panel");
  });

  it("names what still works, which is what makes it actionable", () => {
    expect(notice?.stillWorks).toContain(
      "The anchors this feed already contributed, which are retained and marked possibly stale",
    );
    expect(notice?.stillWorks).toContain("Solving the week, and writing the plan to your calendar");
  });

  it("carries when it last succeeded, so the panel can state the age", () => {
    expect(notice?.since).toBe(new Date(NOW - 30 * HOUR).toISOString());
  });

  it("states that the anchors are retained and marked possibly stale rather than removed", () => {
    expect(notice?.detail).toContain("retained and marked possibly stale");
  });

  it("names the threshold, so the reader knows why it appeared now", () => {
    expect(notice?.detail).toContain(String(STALE_AFTER_HOURS));
  });

  it("says instead that nothing has ever been read where there was no success", () => {
    expect(staleFeedNotice(failing(null), NOW)?.detail).toContain("never been read successfully");
  });

  it("is absent while the feed reads, so a working source raises nothing", () => {
    expect(staleFeedNotice(buildSource(), NOW)).toBeNull();
  });

  it("is scoped to the source it is about", () => {
    expect(notice?.scope?.sourceId).toBe(failing(30).id);
    expect(notice?.scope?.screen).toBe("settings");
  });
});

describe("the panel a parse rejection raises", () => {
  const rejected = buildSource({
    syncState: buildSyncState({
      rejectedCount: 3,
      rejections: [
        {
          kind: "unknown-zone",
          line: 41,
          component: "VEVENT",
          detail: "TZID=Mars/Olympus",
          uid: null,
        },
        {
          kind: "unknown-zone",
          line: 88,
          component: "VEVENT",
          detail: "TZID=Mars/Olympus",
          uid: null,
        },
        {
          kind: "missing-duration",
          line: 120,
          component: "VEVENT",
          detail: "no DTEND and no DURATION",
          uid: null,
        },
      ],
    }),
  });

  it("states how many events were rejected", () => {
    expect(rejectionNotice(rejected)?.title).toContain("3 events");
  });

  it("states the count per class, which is what a reader can act on", () => {
    expect(rejectionNotice(rejected)?.detail).toContain("2 unknown-zone");
    expect(rejectionNotice(rejected)?.detail).toContain("1 missing-duration");
  });

  it("names what still works, so a partial read does not read as a lost feed", () => {
    expect(rejectionNotice(rejected)?.stillWorks.length).toBeGreaterThan(0);
  });

  it("uses the singular for one rejection, because a count is read as a sentence", () => {
    const one = buildSource({
      syncState: buildSyncState({
        rejectedCount: 1,
        rejections: [
          { kind: "malformed-value", line: 7, component: "VEVENT", detail: "DTSTART", uid: null },
        ],
      }),
    });

    expect(rejectionNotice(one)?.title).toContain("1 event in");
  });

  it("is absent while nothing was rejected", () => {
    expect(rejectionNotice(buildSource())).toBeNull();
  });

  /* The api reports a count and may report no rows for it, and a panel that then said `` for the classes would be
   * worse than one that says it does not know. */
  it("says the classes are unknown where the count has no rows behind it", () => {
    const counted = buildSource({
      syncState: buildSyncState({ rejectedCount: 2, rejections: [] }),
    });

    expect(rejectionNotice(counted)?.detail).toContain("did not say which components");
  });
});

describe("every panel the screen raises about its sources", () => {
  it("raises both for one source that is stale and rejecting", () => {
    const source = buildSource({
      syncState: buildSyncState({
        lastError: "The feed answered 503.",
        lastSuccessAt: new Date(NOW - 30 * HOUR).toISOString(),
        rejectedCount: 1,
        rejections: [
          { kind: "unknown-zone", line: 41, component: "VEVENT", detail: "TZID", uid: null },
        ],
      }),
    });

    expect(sourcePanelNotices([source], NOW).map((notice) => notice.pigment)).toEqual([
      "amber",
      "amber",
    ]);
  });

  /* An excluded source contributes zero anchors because the reader asked it to, so reporting its stale state
   * would be telling them something broke when they turned it off themselves. */
  it("raises nothing for an excluded source, whatever its last attempt did", () => {
    const excluded = buildSource({
      id: SOURCE_PERSONAL,
      included: false,
      state: "excluded",
      syncState: buildSyncState({
        lastError: "The feed answered 503.",
        lastSuccessAt: new Date(NOW - 300 * HOUR).toISOString(),
      }),
    });

    expect(sourcePanelNotices([excluded], NOW)).toEqual([]);
  });

  it("raises nothing at all for sources that read", () => {
    expect(sourcePanelNotices([buildSource()], NOW)).toEqual([]);
  });
});
