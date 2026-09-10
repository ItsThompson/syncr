/* THE VOLUME AND THE PIGMENT OF EVERY CASE THE PRODUCT CAN RAISE, AND THE FOURTH VOLUME THAT DOES NOT EXIST.
 *
 * VOLUME IS POSITION AND PIGMENT IS KIND, which is two questions and therefore two fields: how loudly a reader
 * should care, and what sort of thing happened. Section 16 assigns both per case, and the cases below are called
 * through the factories the screens themselves call, so what is asserted is the value a reader would meet rather
 * than a table restating a table.
 *
 * LEVEL 4 IS DELIBERATELY UNUSED. syncr does not block a reader over a degradation: infeasibility is the product's
 * most valuable output, and a week that cannot hold its commitments is impossible rather than broken. There is no
 * blocking volume in the vocabulary, no notice declares one, and the kit exports no dialog for one.
 *
 * THE SET OF CASES IS BOUNDED BY THE TREE, not by this file. `shippedNotices` finds every notice the application
 * declares by parsing for the shape -- an object carrying a volume and a surviving-capability list -- so a
 * fourteenth module raising one is reported here whether anyone remembered to add a case or not. That is what
 * makes the sweep an audit rather than a second copy of section 16. */

import { describe, expect, it } from "vitest";

import { NARROWING_MODULE, shippedNotices, type NoticeLiteral } from "../../testing/noticeLiterals";
import { captureRefusedNotice } from "../../app/capture/refusals";
import {
  captureNotSavedNotice,
  preferredTimeNotSavedNotice,
} from "../../app/notices/refusedWrites";
import { completionRefusedNotice, taskCompletedNotice } from "../backlog/notices";
import { rejectionNotice } from "../settings/sourceNotices";
import {
  backfillSettledNotice,
  confirmationRefusedNotice,
  recordingRefusedNotice,
  unconfirmedNotice,
} from "../today/notices";
import { conflictNotice, refusedNotice, solveFailedNotice } from "../week/notices";
import { SOURCE_TIMETABLE, buildSource, buildSyncState } from "../settings/__tests__/fixtures";
import type { Notice, NoticePigment, NoticeVolume } from "../../ui/domain";
import { noticesAt } from "../../ui/domain";
import type { Problem } from "../../contract";

const VOLUMES: readonly NoticeVolume[] = ["inline", "panel", "banner"];
const PIGMENTS: readonly NoticePigment[] = ["info", "amber", "oxide", "verdigris"];

const REFUSED: Problem = {
  type: "syncr:conflict",
  title: "This proposal has been replaced",
  status: 409,
  detail: "A newer proposal replaced the one you approved, so nothing was applied.",
};

/** Section 16's cases, each raised by the factory the screen raising it calls. */
const CASES: readonly { readonly case: string; readonly notice: Notice }[] = [
  {
    case: "an external commitment overlaps a planned block",
    notice: conflictNotice("c1", "A commitment overlaps this block.", "b1"),
  },
  {
    case: "the solver returned no plan",
    notice: solveFailedNotice({
      operationId: "o1",
      statement: "This work could not complete.",
      attempt: 3,
      code: "solver_timeout",
      message: "no plan within the budget",
    }),
  },
  { case: "a write on the week was refused", notice: refusedNotice("approve", REFUSED) },
  { case: "a day nobody has answered for", notice: unconfirmedNotice("2026-02-09", 2) },
  {
    case: "a recording the api refused",
    notice: recordingRefusedNotice("b1", REFUSED),
  },
  {
    case: "a confirmation the api refused",
    notice: confirmationRefusedNotice("2026-02-09", REFUSED),
  },
  {
    case: "a backfill that settled past days",
    notice: backfillSettledNotice("2026-02-09", "3 days confirmed.", 0),
  },
  { case: "a capture the api refused", notice: captureRefusedNotice(REFUSED) },
  {
    case: "a capture the api refused after the form that asked for it had gone",
    notice: captureNotSavedNotice(REFUSED),
  },
  {
    case: "a task that landed whose own preferred time the api refused",
    notice: preferredTimeNotSavedNotice(REFUSED),
  },
  { case: "a task completed elsewhere", notice: taskCompletedNotice("Past papers") },
  { case: "a completion the api refused", notice: completionRefusedNotice(REFUSED) },
  {
    case: "a feed with rejected components",
    notice: expected(
      rejectionNotice(
        buildSource({
          syncState: buildSyncState({
            rejectedCount: 2,
            rejections: [
              { kind: "unknown-zone", component: "VEVENT", detail: "line 12", line: 12 },
              { kind: "missing-duration", component: "VEVENT", detail: "line 40", line: 40 },
            ],
          }),
        }),
      ),
      "the rejection panel",
    ),
  },
];

/** A factory that answers null when its condition is absent, asserted to have answered here. */
function expected(notice: Notice | null, what: string): Notice {
  if (notice === null) throw new Error(`${what} was not raised, so the case below asserts nothing`);
  return notice;
}

/** The api's notice about an unreadable feed, in the wire shape both surfaces are handed. */
function unreadableFeedNotices(): readonly Notice[] {
  return noticesAt("panel", [
    {
      id: `calendar.feed-stale.${SOURCE_TIMETABLE}`,
      volume: "panel",
      pigment: "amber",
      title: "Timetable could not be read",
      detail:
        "The feed did not answer. It last answered a day ago. A feed is reported once it has been failing " +
        "for more than 12 hours.",
      unavailable: ["Reading new commitments from Timetable"],
      stillWorks: [
        "The commitments this feed already contributed, which are retained and marked possibly stale",
        "Solving the week, which still plans around every commitment already read",
      ],
      since: new Date(Date.now() - 30 * 60 * 60 * 1000).toISOString(),
      action: null,
      scope: { screen: "settings", sourceId: SOURCE_TIMETABLE },
    },
  ]);
}

describe("every case the product raises", () => {
  it.each(CASES)(
    "$case takes a volume and a pigment from the closed vocabularies",
    ({ notice }) => {
      expect(VOLUMES).toContain(notice.volume);
      expect(PIGMENTS).toContain(notice.pigment);
    },
  );

  it.each(CASES)("$case names at least one capability that survives it", ({ notice }) => {
    expect(notice.stillWorks.length).toBeGreaterThan(0);
    for (const capability of notice.stillWorks) expect(capability.trim()).not.toBe("");
  });

  /* THE ONE THE SHELL'S TABLE SINGLES OUT. An unconfirmed day must read as the ordinary state of a day rather
   * than as something wrong; amber would teach a reader to distrust it. */
  it("states an unconfirmed day informationally, spending no signal pigment", () => {
    expect(unconfirmedNotice("2026-02-09", 0).pigment).toBe("info");
  });

  /* THE UNREADABLE FEED IS NOT IN THE CASES ABOVE, because no client module composes it any more: the api words
   * it and both surfaces render what arrives. What is asserted here is against the WIRE SHAPE the surfaces are
   * handed, which the api composes once: amber, because nothing is broken, naming what survives. Its threshold
   * and its words are pinned where they are composed, on the api. */
  it("states an unreadable feed in amber, in the one notice the api composes for both surfaces", () => {
    const [feedPanel] = unreadableFeedNotices();

    expect(feedPanel.pigment).toBe("amber");
    expect(feedPanel.volume).toBe("panel");
    expect(feedPanel.stillWorks.length).toBeGreaterThan(0);
  });

  /* THE TWO THE CLIENT COMPOSES ITSELF, which are the two halves of one gesture: a write the reader's own surface
   * did not survive to receive takes the loudest non-blocking volume, because it is the only one that outlives the
   * screen they have moved on to, and oxide because a durable write did not happen. It is the assignment the write
   * target's expiry already carries. Both are asserted, because a capture sends two writes and each has its own
   * sentence: one says the task is gone and one says the task is there without its preferred time. */
  it("states a write that did not happen in oxide, in the top bar, wherever the reader now is", () => {
    const capture = captureNotSavedNotice(REFUSED);
    const preference = preferredTimeNotSavedNotice(REFUSED);

    expect([capture.volume, capture.pigment]).toEqual(["banner", "oxide"]);
    expect([preference.volume, preference.pigment]).toEqual(["banner", "oxide"]);
    /* Two ids, because one condition stands once under its own id: a shared id would replace the other's banner
       and a reader who met both would be told only the second. */
    expect(capture.id).not.toBe(preference.id);
  });

  it("offers at most one repair per notice, so a reader is never asked to choose between two", () => {
    for (const { notice } of CASES)
      expect(notice.action === null || notice.action.href).toBeTruthy();
  });
});

describe("every notice the application declares, found by parsing for the shape", () => {
  it("declares a volume this product has, which is three and not four", async () => {
    const declared = await composed();

    /* AN EXACT COUNT rather than a floor. `>` kept passing if the parse narrowed: the Python teardown guard's own
     * suffix case records why that matters -- ">= 2 passed with three suffixes, and would keep passing if the walk
     * narrowed to two, which is how the systemd units came to be invisible". A notice added or removed is a
     * deliberate change and reddens here with the figure. */
    expect(declared).toHaveLength(20);
    expect(unreadable(declared, (one) => one.volume)).toEqual([]);
    for (const one of declared) expect(VOLUMES).toContain(one.volume);
  });

  it("declares a pigment from the four kinds", async () => {
    const declared = await composed();

    expect(unreadable(declared, (one) => one.pigment)).toEqual([]);
    for (const one of declared) expect(PIGMENTS).toContain(one.pigment);
  });

  /* THE WHOLE POINT OF THE PARSE. The type refuses an empty list at compile time and the api's schema refuses one
   * before it is serialized; this answers the question neither does, which is whether any notice exists whose list
   * nobody has read. An unresolved list is a failure for the same reason an empty one is. */
  it("names a surviving capability, in every notice, in every module", async () => {
    const declared = await composed();

    expect(declared.filter((one) => one.stillWorks !== "non-empty").map(where)).toEqual([]);
  });

  it("is spread across the modules that raise them, and the set of modules is exact", async () => {
    const files = [...new Set((await composed()).map((one) => one.file))].toSorted();

    /* THE SET, not a floor, for the reason above: a scan that narrowed from eight modules to five would keep
     * passing a `>= 8` written when there were twelve. Each of these is a module that composes notices in the
     * words this product wrote. */
    expect(files).toEqual([
      "app/capture/refusals.ts",
      "app/notices/refusedWrites.ts",
      "routes/areas/components/ResidualNotices.tsx",
      "routes/backlog/notices.ts",
      "routes/settings/sourceNotices.ts",
      "routes/templates/rejection.ts",
      "routes/today/notices.ts",
      "routes/week/notices.ts",
    ]);
  });

  /* ONE MODULE MAY BUILD A NOTICE FROM VALUES RATHER THAN FROM WORDS, and this is the assertion that keeps it one.
   * A second file whose notices carry an unreadable volume or an empty list would fail the three rules above, which
   * is exactly what should happen: the latitude is declared, not inferred. */
  it("leaves exactly one narrowing module, whose two literals are the two the type documents", async () => {
    const narrowed = (await shippedNotices()).filter((one) => one.file === NARROWING_MODULE);

    expect(narrowed).toHaveLength(2);
    /* Neither carries a literal volume, because both take the api's. One provably builds a non-empty list from the
     * wire's first element, and the other is the total outage, which names nothing on purpose. */
    expect(narrowed.map((one) => one.volume)).toEqual([null, null]);
    expect(narrowed.map((one) => one.stillWorks).toSorted()).toEqual(["empty", "non-empty"]);
  });
});

function where(one: NoticeLiteral): string {
  return `${one.file}:${String(one.line)} stillWorks is ${one.stillWorks}`;
}

/*
 * The notices this product COMPOSES, in words it wrote.
 *
 * The narrowing module is separated rather than skipped, and the separation is asserted: it is where a wire notice
 * becomes the kit's type, so both of its literals take the api's own volume and one of them is the total-outage
 * case, which is the single shape allowed to name nothing. Every rule above is about the composed ones.
 */
async function composed(): Promise<NoticeLiteral[]> {
  return (await shippedNotices()).filter((one) => one.file !== NARROWING_MODULE);
}

function unreadable(
  declared: readonly NoticeLiteral[],
  read: (one: NoticeLiteral) => string | null,
): string[] {
  return declared
    .filter((one) => read(one) === null)
    .map((one) => `${one.file}:${String(one.line)}`);
}
