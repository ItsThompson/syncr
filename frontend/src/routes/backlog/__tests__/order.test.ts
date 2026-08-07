/* THE ORDER, over the cases a naive comparison gets wrong.
 *
 * WHY THESE ARE VALUE TESTS AND NOT RENDERINGS. The order is a fact about the read rather than about the markup:
 * `Table` draws the rows it is given in the order it is given them, so what has to be right is this function. The
 * screen's own test drives that pressing a header reorders the table and reads nothing again. */

import { describe, expect, it } from "vitest";

import { AREA_CAREER, AREA_FITNESS, buildTask } from "./fixtures";
import { DEFAULT_SORT, ordered } from "../order";

const NAMES: Record<string, string> = { [AREA_CAREER]: "Career", [AREA_FITNESS]: "Fitness" };
const areaName = (areaId: string): string => NAMES[areaId] ?? "";

const titlesOf = (tasks: readonly { title: string }[]): string[] => tasks.map((task) => task.title);

describe("the deadline column", () => {
  it("puts the soonest deadline first", () => {
    const rows = [
      buildTask({ id: "a", title: "later", deadline: "2026-02-20T09:00:00Z" }),
      buildTask({ id: "b", title: "sooner", deadline: "2026-02-13T09:00:00Z" }),
    ];

    expect(titlesOf(ordered(rows, { key: "deadline", direction: "ascending" }, areaName))).toEqual([
      "sooner",
      "later",
    ]);
  });

  /* A NULL IS NOT A VALUE AT ONE END OF THE RANGE. A task with no deadline is not due first and is not due last:
     it is not due. Sorting it to the top of a descending column would put the rows a reader sorted by deadline in
     order to see under the rows that have none. */
  it("keeps the tasks with no deadline after the ones that have one, in both directions", () => {
    const rows = [
      buildTask({ id: "a", title: "undated" }),
      buildTask({ id: "b", title: "sooner", deadline: "2026-02-13T09:00:00Z" }),
      buildTask({ id: "c", title: "later", deadline: "2026-02-20T09:00:00Z" }),
    ];

    expect(titlesOf(ordered(rows, { key: "deadline", direction: "ascending" }, areaName))).toEqual([
      "sooner",
      "later",
      "undated",
    ]);
    expect(titlesOf(ordered(rows, { key: "deadline", direction: "descending" }, areaName))).toEqual(
      ["later", "sooner", "undated"],
    );
  });

  it("is the order the screen opens on, because a backlog is read by what is due", () => {
    expect(DEFAULT_SORT).toEqual({ key: "deadline", direction: "ascending" });
  });
});

describe("the other columns", () => {
  it("orders the Area column by the name a reader sees, not by the identifier", () => {
    /* The Fitness identifier sorts BEFORE the Career one as text, so a comparison over ids would answer the
       other way round and nothing on screen would say why. */
    const rows = [
      buildTask({ id: "a", title: "fitness one", areaId: AREA_FITNESS }),
      buildTask({ id: "b", title: "career one", areaId: AREA_CAREER }),
    ];

    expect(titlesOf(ordered(rows, { key: "area", direction: "ascending" }, areaName))).toEqual([
      "career one",
      "fitness one",
    ]);
  });

  it("orders priority by how much the objective prefers it rather than by the alphabet", () => {
    const rows = [
      buildTask({ id: "a", title: "normal one", priority: "normal" }),
      buildTask({ id: "b", title: "urgent one", priority: "urgent" }),
      buildTask({ id: "c", title: "low one", priority: "low" }),
      buildTask({ id: "d", title: "high one", priority: "high" }),
    ];

    expect(titlesOf(ordered(rows, { key: "priority", direction: "descending" }, areaName))).toEqual(
      ["urgent one", "high one", "normal one", "low one"],
    );
  });

  it("orders remaining work as a number", () => {
    const rows = [
      buildTask({ id: "a", title: "nine", remainingMinutes: 9 }),
      buildTask({ id: "b", title: "eighty", remainingMinutes: 80 }),
      buildTask({ id: "c", title: "one hundred", remainingMinutes: 100 }),
    ];

    expect(titlesOf(ordered(rows, { key: "remaining", direction: "ascending" }, areaName))).toEqual(
      ["nine", "eighty", "one hundred"],
    );
  });
});

describe("what the order does not do", () => {
  it("leaves the rows as they came for a column it cannot order by", () => {
    const rows = [buildTask({ id: "a", title: "first" }), buildTask({ id: "b", title: "second" })];

    expect(titlesOf(ordered(rows, { key: "chunk", direction: "descending" }, areaName))).toEqual([
      "first",
      "second",
    ]);
  });

  it("does not reorder the array it was given, which is the read's own cached value", () => {
    const rows = [
      buildTask({ id: "a", title: "later", deadline: "2026-02-20T09:00:00Z" }),
      buildTask({ id: "b", title: "sooner", deadline: "2026-02-13T09:00:00Z" }),
    ];

    ordered(rows, { key: "deadline", direction: "ascending" }, areaName);

    expect(titlesOf(rows)).toEqual(["later", "sooner"]);
  });

  /* Two rows that compare equal keep one order between two renders. Without the tie-break they would swap under
     a reader whenever the read returned them in a different order. */
  it("breaks a tie by identifier, so an equal pair does not swap between renders", () => {
    const rows = [
      buildTask({ id: "b2", title: "second", deadline: "2026-02-13T09:00:00Z" }),
      buildTask({ id: "a1", title: "first", deadline: "2026-02-13T09:00:00Z" }),
    ];

    expect(titlesOf(ordered(rows, { key: "deadline", direction: "ascending" }, areaName))).toEqual([
      "first",
      "second",
    ]);
    expect(titlesOf(ordered(rows, { key: "deadline", direction: "descending" }, areaName))).toEqual(
      ["first", "second"],
    );
  });
});
