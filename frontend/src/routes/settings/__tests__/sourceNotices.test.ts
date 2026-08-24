/* The one panel this screen still composes -- the parse rejection -- and the field the kit's type will not let it
 * omit.
 *
 * THE STALENESS CASES LIVE WITH THE COMPOSER now. Whether a feed counts as stale is decided by the api, on
 * `packages/syncr-api/tests/test_feed_notices.py`; this screen renders the notice that read produces. What is
 * asserted here is only what this module itself words.
 *
 * `stillWorks` IS THE CLAIM UNDER TEST here, not a detail. Every degradation notice in this product names the
 * capability that survives, and for a rejected read a great deal does: the anchors already read are retained and
 * marked possibly stale, and the week still solves and still reaches the calendar. A notice that said only what
 * broke would leave a reader unable to decide whether to plan around what they can see. */

import { describe, expect, it } from "vitest";

import { rejectionNotice, rejectionPanels } from "../sourceNotices";
import { SOURCE_PERSONAL, buildSource, buildSyncState } from "./fixtures";

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

describe("every panel this screen composes about its sources", () => {
  /* The unreadable feed is NOT among them, whatever its sync state says: its panel arrives on the source list,
   * composed by the api, so a failing feed alone raises nothing here. */
  it("composes no panel for a feed that can no longer be read", () => {
    const stale = buildSource({ state: "error" });

    expect(rejectionPanels([stale])).toEqual([]);
  });

  /* An excluded source contributes zero anchors because the reader asked it to, so reporting its state would be
   * telling them something broke when they turned it off themselves. */
  it("raises nothing for an excluded source, whatever was rejected in its last read", () => {
    const excluded = buildSource({
      id: SOURCE_PERSONAL,
      included: false,
      state: "excluded",
      syncState: buildSyncState({
        rejectedCount: 2,
        rejections: [
          { kind: "unknown-zone", line: 41, component: "VEVENT", detail: "TZID", uid: null },
        ],
      }),
    });

    expect(rejectionPanels([excluded])).toEqual([]);
  });

  it("raises the rejection panel beside the source that caused it, in source order", () => {
    const rejecting = buildSource({
      id: SOURCE_PERSONAL,
      syncState: buildSyncState({
        rejectedCount: 1,
        rejections: [
          { kind: "unknown-zone", line: 41, component: "VEVENT", detail: "TZID", uid: null },
        ],
      }),
    });

    expect(rejectionPanels([buildSource(), rejecting]).map((notice) => notice.id)).toEqual([
      `calendar.feed-rejections.${rejecting.id}`,
    ]);
  });
});
