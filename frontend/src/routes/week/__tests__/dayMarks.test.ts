import { describe, expect, it } from "vitest";

import { staleDayMark, unconfirmedDayMark } from "../notices";

const DATE = "2026-02-09";
const SOURCE_ID = "8c2e0d4f-6a12-4f3a-8b21-7d2b1a904c70";

describe("a stale calendar source on a day", () => {
  it("pairs the amber header mark with an inline notice that names what remains available", () => {
    const mark = staleDayMark(DATE, SOURCE_ID);

    expect(mark.pigment).toBe("amber");
    expect(mark.notice).toMatchObject({
      volume: "inline",
      pigment: "amber",
      scope: { screen: "/week", date: DATE, sourceId: SOURCE_ID },
    });
    expect(mark.notice.stillWorks).toEqual([
      "the plan on the grid, which still respects the commitments already read",
      "solving the week around the commitments already read",
    ]);
  });

  it("pairs an unconfirmed day with an informational mark", () => {
    const mark = unconfirmedDayMark(DATE);

    expect(mark.pigment).toBe("info");
    expect(mark.notice).toMatchObject({
      volume: "inline",
      pigment: "info",
      scope: { screen: "/week", date: DATE },
    });
    expect(mark.notice.stillWorks).toEqual(["confirming this day", "the plan on the grid"]);
  });
});
