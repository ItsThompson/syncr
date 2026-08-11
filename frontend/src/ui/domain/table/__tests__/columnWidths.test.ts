/* THE COLUMN POLICY'S ARITHMETIC, AND THE EQUALITIES A CONVENIENT FIXTURE WOULD HIDE.
 *
 * Every case below differs from its neighbours in exactly one thing, because the defects this function can carry
 * are all equalities: two columns given the same share, a share taken over the wrong total, a subtrahend that
 * drops a term, an order that happens to be symmetric. So no two weights in a case are equal, no two lengths are
 * equal, and the declared columns are never in a position where reversing them would produce the same answer.
 *
 * WHAT IS ASSERTED IS THE EXPRESSION, not a pixel: the widths are CSS the browser resolves, and jsdom lays out
 * nothing. The rendered composition is asserted through the component in `table.test.tsx`. */

import { describe, expect, it } from "vitest";

import { columnWidthsOf, type TableColumnWidth } from "../columnWidths";

const NOTHING: readonly string[] = [];
const MARK = "var(--table-mark-w)";

describe("a table where no column declares a width", () => {
  it("is not given widths at all, so the browser lays it out from its content as before", () => {
    expect(columnWidthsOf([undefined, undefined], NOTHING)).toBeNull();
  });

  it("is not given widths by the reserved lengths alone, which are not a column's declaration", () => {
    expect(columnWidthsOf([undefined, undefined], [MARK])).toBeNull();
  });

  it("is not given widths when it has no columns at all", () => {
    expect(columnWidthsOf([], NOTHING)).toBeNull();
  });
});

describe("a length a column declares", () => {
  it("is the width that column takes, verbatim, whatever unit it is written in", () => {
    const widths = columnWidthsOf(["236px", "11ch"], NOTHING);

    expect(widths).toEqual(["236px", "11ch"]);
  });

  it("leaves the rest of the width to the column that declares nothing", () => {
    const widths = columnWidthsOf(["236px", undefined], NOTHING);

    expect(widths).toEqual(["236px", "calc(100% - (236px))"]);
  });

  it("is subtracted with every other length, so a column beside two of them gets what both leave", () => {
    const widths = columnWidthsOf(["236px", "88px", undefined], NOTHING);

    expect(widths).toEqual(["236px", "88px", "calc(100% - (236px + 88px))"]);
  });

  it("keeps its place when it is declared after the column that absorbs, not only before it", () => {
    const widths = columnWidthsOf([undefined, "88px"], NOTHING);

    expect(widths).toEqual(["calc(100% - (88px))", "88px"]);
  });
});

/* WHAT A LENGTH IS EXACT IN, WHICH IS A TABLE WHERE SOME COLUMN CLAIMS A SHARE.
 *
 * The lengths are subtracted and the shares divide what is left, so a length is exact while one column absorbs the
 * difference between the lengths and the table. Declare a length on every column and nothing claims a share:
 * these cases pin what this function emits then, which is the lengths and no expression at all. What the browser
 * does with them is the constraint a caller meets here rather than in a review -- a fixed layout has nothing to
 * take the difference from, so it scales every column, the reserved gutter with them, and lengths adding up past
 * the container overflow it. `probe/table.probe.test.tsx` measures that. */
describe("a table whose every column declares a length", () => {
  it("is given those lengths and no share, so nothing is left to absorb what they do not fill", () => {
    const widths = columnWidthsOf(["236px", "88px"], NOTHING);

    expect(widths).toEqual(["236px", "88px"]);
    expect(widths?.some((width) => width.includes("calc"))).toBe(false);
  });

  it("leaves a reserved length unabsorbed too, which is why the gutter is scaled with the rest", () => {
    const widths = columnWidthsOf(["236px", "88px"], [MARK]);

    expect(widths).toEqual(["236px", "88px"]);
  });
});

describe("a weight a column declares", () => {
  it("takes the whole surplus when it is the only share claimed", () => {
    const widths = columnWidthsOf([{ weight: 3 }, "88px"], NOTHING);

    expect(widths).toEqual(["calc(100% - (88px))", "88px"]);
  });

  it("divides the surplus in the ratio of the weights, and not equally", () => {
    const widths = columnWidthsOf([{ weight: 3 }, { weight: 1 }, "88px"], NOTHING);

    expect(widths).toEqual([
      "calc((100% - (88px)) * 3 / 4)",
      "calc((100% - (88px)) * 1 / 4)",
      "88px",
    ]);
  });

  it("counts a column that declares nothing as one share, so the two divide the surplus", () => {
    const widths = columnWidthsOf([{ weight: 3 }, undefined, "88px"], NOTHING);

    expect(widths).toEqual([
      "calc((100% - (88px)) * 3 / 4)",
      "calc((100% - (88px)) * 1 / 4)",
      "88px",
    ]);
  });

  it("divides the table itself when no column declares a length", () => {
    const widths = columnWidthsOf([{ weight: 3 }, { weight: 1 }], NOTHING);

    expect(widths).toEqual(["calc((100%) * 3 / 4)", "calc((100%) * 1 / 4)"]);
  });

  it("claims nothing at zero, and the columns that do claim a share still divide the surplus", () => {
    const widths = columnWidthsOf([{ weight: 0 }, { weight: 2 }, "88px"], NOTHING);

    expect(widths).toEqual(["0px", "calc(100% - (88px))", "88px"]);
  });

  it("claims nothing when a caller writes it negative, rather than emitting a width nothing resolves", () => {
    const widths = columnWidthsOf([{ weight: -2 }, { weight: 2 }], NOTHING);

    expect(widths).toEqual(["0px", "calc(100%)"]);
  });
});

describe("a length the table spends outside the caller's columns", () => {
  it("comes out of the surplus, so the columns do not divide width the table has already spent", () => {
    const widths = columnWidthsOf([{ weight: 1 }], [MARK]);

    expect(widths).toEqual(["calc(100% - (var(--table-mark-w)))"]);
  });

  it("is subtracted before the declared lengths, so both are named and neither is dropped", () => {
    const widths = columnWidthsOf(["236px", { weight: 1 }], [MARK]);

    expect(widths).toEqual(["236px", "calc(100% - (var(--table-mark-w) + 236px))"]);
  });

  it("is named beside every other one, so a table spending two lengths outside its columns names both", () => {
    const widths = columnWidthsOf([{ weight: 1 }], [MARK, "24px"]);

    expect(widths).toEqual(["calc(100% - (var(--table-mark-w) + 24px))"]);
  });

  it("is absent from the expression when the table spends nothing outside its columns", () => {
    const widths = columnWidthsOf(["236px", { weight: 1 }], NOTHING);

    expect(widths).toEqual(["236px", "calc(100% - (236px))"]);
  });
});

describe("the answer has one entry per column", () => {
  it.each([1, 2, 3, 7])("keeps the caller's order and count at %i columns", (count) => {
    const declared: (TableColumnWidth | undefined)[] = Array.from({ length: count }, (_, index) =>
      index === 0 ? "40px" : undefined,
    );

    const widths = columnWidthsOf(declared, NOTHING);

    expect(widths).toHaveLength(count);
    expect(widths?.[0]).toBe("40px");
  });
});
