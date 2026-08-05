/* WHAT REACHES THE DOM: the tier ladder, the glyph slot's precedence, the state attributes, and the geometry a
 * block is positioned by.
 *
 * jsdom applies no stylesheet, so what a rendering can answer is which ATTRIBUTE and which computed length a block
 * carries, and what a reader hears. What a rule DECLARES is `stylesheet.test.ts`'s question, and what a browser
 * paints is a browser's. All three are needed and none substitutes for another.
 *
 * The combinations are section 15's own table rather than a sample, because in the language syncr inherits four
 * plausible state systems each looked correct on a single state and produced two pixel-identical rows in a
 * combination matrix while meaning different things. */

import { cleanup, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Block, type BlockPlacement, type BlockStates } from "../Block";
import { ForbiddenBand } from "../ForbiddenBand";
import { NowRule } from "../NowRule";
import { BLOCK_H_COMPACT_PX, BLOCK_H_LABEL_PX, BLOCK_H_SLIVER_PX } from "../metrics";
import { placeOverlaps } from "../overlap";
import { titleLineCount } from "../tiers";
import type { GridBlock } from "../types";

const FULL_WIDTH: BlockPlacement = {
  topPx: 0,
  heightPx: 26,
  across: {
    left: 0,
    right: 0,
    indentSteps: 0,
    layer: 0,
    overlapCount: null,
    isSplit: false,
  },
};

function gridBlock(overrides: Partial<GridBlock> = {}): GridBlock {
  return {
    id: "b1",
    title: "Leetcode · Graphs",
    span: { startMin: 540, endMin: 570 },
    origin: "task",
    pigment: "01",
    areaName: "Career",
    isPinned: false,
    ...overrides,
  };
}

/** The one mark in the slot, or null where nothing claimed it. */
const slotOf = (element: HTMLElement): Element | null => element.querySelector(".glyph-slot");

function renderBlock(
  block: Partial<GridBlock> = {},
  placement: Partial<BlockPlacement> = {},
  states?: BlockStates,
): HTMLElement {
  const { container } = render(
    <Block
      block={gridBlock(block)}
      placement={{
        ...FULL_WIDTH,
        ...placement,
        across: { ...FULL_WIDTH.across, ...placement.across },
      }}
      states={states}
    />,
  );
  const element = container.firstElementChild;
  if (!(element instanceof HTMLElement)) throw new Error("the block rendered nothing");
  return element;
}

describe("the tier ladder as it reaches the DOM", () => {
  it.each([
    [40, "label"],
    [BLOCK_H_LABEL_PX, "label"],
    [BLOCK_H_COMPACT_PX, "compact"],
    [BLOCK_H_SLIVER_PX, "sliver"],
    [4, "hairline"],
  ])("carries data-tier=%s at %spx", (heightPx, tier) => {
    expect(renderBlock({}, { heightPx })).toHaveAttribute("data-tier", tier);
  });

  /* One height per case, so nothing has to be cleaned out of the DOM between iterations: the first draft rendered
   * three blocks into one test and then removed the nodes it had just found, which is a test tidying up after itself
   * rather than asserting. */
  it.each([40, BLOCK_H_LABEL_PX, BLOCK_H_COMPACT_PX])("draws the title at %spx", (heightPx) => {
    render(<Block block={gridBlock()} placement={{ ...FULL_WIDTH, heightPx }} />);

    expect(screen.getByText("Leetcode · Graphs")).toBeInTheDocument();
  });

  it("draws NO title element below them, rather than hiding one with a rule", () => {
    for (const heightPx of [BLOCK_H_SLIVER_PX, 4]) {
      const element = renderBlock({}, { heightPx });

      expect(element.querySelector(".week-block__title")).toBeNull();
    }
  });

  it("KEEPS THE TITLE AVAILABLE at every tier, so the sliver tier is never a dead end", () => {
    for (const heightPx of [40, BLOCK_H_LABEL_PX, BLOCK_H_COMPACT_PX, BLOCK_H_SLIVER_PX, 4]) {
      expect(renderBlock({}, { heightPx })).toHaveAttribute(
        "aria-label",
        "Leetcode · Graphs · Career",
      );
    }
  });

  it("passes the computed line count to the clamp rather than a fixed one", () => {
    for (const heightPx of [BLOCK_H_LABEL_PX, 40, 80, 130]) {
      expect(renderBlock({}, { heightPx }).style.getPropertyValue("--lines")).toBe(
        String(titleLineCount(heightPx)),
      );
    }
  });
});

describe("the glyph slot's precedence", () => {
  it("shows the origin mark below the label tiers and NOT at them", () => {
    expect(slotOf(renderBlock({}, { heightPx: BLOCK_H_SLIVER_PX }))?.className).toContain(
      "glyph--origin-task",
    );
    expect(slotOf(renderBlock({}, { heightPx: 40 }))).toBeNull();
  });

  it("gives the pin the slot over the origin mark at the sliver tier", () => {
    const element = renderBlock({ isPinned: true }, { heightPx: BLOCK_H_SLIVER_PX });

    expect(slotOf(element)?.className).toContain("glyph--pinned");
    expect(slotOf(element)?.className).not.toContain("glyph--origin");
  });

  it("gives the overlap count the slot over the proposal-source mark", () => {
    const element = renderBlock(
      {},
      { across: { ...FULL_WIDTH.across, overlapCount: 5 } },
      { isProposalSource: true },
    );

    expect(slotOf(element)?.className).toContain("glyph--overlap");
    expect(slotOf(element)?.textContent).toBe("5");
  });

  it("gives the pin the slot over the overlap count, which is the strongest reason in the system", () => {
    const element = renderBlock(
      { isPinned: true },
      { across: { ...FULL_WIDTH.across, overlapCount: 5 } },
    );

    expect(slotOf(element)?.className).toContain("glyph--pinned");
  });

  it("leaves the slot empty at a label tier with nothing to claim it", () => {
    expect(slotOf(renderBlock({}, { heightPx: 40 }))).toBeNull();
  });
});

describe("the state attributes", () => {
  it("carries none of them at rest, so a resting block is the absence of every state", () => {
    const element = renderBlock();

    for (const attribute of [
      "data-selected",
      "data-conflict",
      "data-proposal",
      "data-pinned",
      "data-split",
    ]) {
      expect(element).not.toHaveAttribute(attribute);
    }
  });

  it.each([
    ["data-selected", { isSelected: true }],
    ["data-conflict", { isConflicted: true }],
    ["data-proposal", { isProposalTarget: true }],
  ])("carries %s when the caller says so and nothing else", (attribute, states: BlockStates) => {
    const element = renderBlock({}, {}, states);

    expect(element).toHaveAttribute(attribute);
  });

  it("carries data-pinned from the block's own fact rather than from a caller's state", () => {
    expect(renderBlock({ isPinned: true })).toHaveAttribute("data-pinned");
  });

  it("carries data-split from the overlap layout, which is where a split comes from", () => {
    const element = renderBlock({}, { across: { ...FULL_WIDTH.across, isSplit: true } });

    expect(element).toHaveAttribute("data-split");
  });

  it("carries data-origin for every origin the domain deals", () => {
    for (const origin of [
      "frame",
      "template_entry",
      "habit",
      "task",
      "anchor",
      "prep",
      "transit",
    ] as const) {
      expect(renderBlock({ origin })).toHaveAttribute("data-origin", origin);
    }
  });
});

/* SECTION 15'S OWN COMBINATION TABLE. Each row is a pair sharing a channel with something, which is the only kind of
 * combination worth asserting: two states on two channels compose by construction. */
describe("every documented combination", () => {
  it("pinned + selected keeps the pin glyph and the state rule", () => {
    const element = renderBlock({ isPinned: true }, {}, { isSelected: true });

    expect(element).toHaveAttribute("data-pinned");
    expect(element).toHaveAttribute("data-selected");
    expect(element.querySelector(".glyph-slot")?.className).toContain("glyph--pinned");
  });

  it("pinned + conflict keeps both, because a pin is a glyph and a conflict is a rule", () => {
    const element = renderBlock({ isPinned: true }, {}, { isConflicted: true });

    expect(element).toHaveAttribute("data-pinned");
    expect(element).toHaveAttribute("data-conflict");
  });

  it("conflict + selected carries both attributes, and the sheet gives conflict the pixel", () => {
    const element = renderBlock({}, {}, { isConflicted: true, isSelected: true });

    expect(element).toHaveAttribute("data-conflict");
    expect(element).toHaveAttribute("data-selected");
  });

  it("proposal + hover carries the attribute, and the CASCADE decides the fill", () => {
    /* Which of the two lands is a cascade question, not a DOM one: the two rules tie on specificity and import order
     * settles it. That half is asserted in `blockStylesheet.test.ts`, where the sheets are read. */
    expect(renderBlock({}, {}, { isProposalTarget: true })).toHaveAttribute("data-proposal");
  });

  it("split + selected carries both, so the split reads from column position", () => {
    const element = renderBlock(
      {},
      { across: { ...FULL_WIDTH.across, isSplit: true } },
      { isSelected: true },
    );

    expect(element).toHaveAttribute("data-split");
    expect(element).toHaveAttribute("data-selected");
  });

  it("sliver + pinned yields the origin mark to the pin", () => {
    const element = renderBlock({ isPinned: true }, { heightPx: BLOCK_H_SLIVER_PX });

    expect(element).toHaveAttribute("data-tier", "sliver");
    expect(element.querySelector(".glyph-slot")?.className).toContain("glyph--pinned");
  });

  it("anchor + conflict keeps the hatch layer and the state rule", () => {
    const element = renderBlock(
      { origin: "anchor", pigment: null, areaName: null },
      {},
      { isConflicted: true },
    );

    expect(element).toHaveAttribute("data-origin", "anchor");
    expect(element).toHaveAttribute("data-conflict");
    expect(element.querySelector(".week-block__hatch")).not.toBeNull();
  });

  it("anchor + hover keeps the hatch, because the hatch is an element and hover is a fill", () => {
    const element = renderBlock({ origin: "anchor", pigment: null, areaName: null });

    expect(element.querySelector(".week-block__hatch")).not.toBeNull();
    expect(element.className).toContain("state-row");
  });

  it("draws the hatch layer for an anchor and for no other origin", () => {
    for (const origin of ["frame", "template_entry", "habit", "task", "prep", "transit"] as const) {
      expect(renderBlock({ origin }).querySelector(".week-block__hatch")).toBeNull();
    }
    expect(renderBlock({ origin: "anchor" }).querySelector(".week-block__hatch")).not.toBeNull();
  });
});

describe("the Area's identity", () => {
  it("reaches the block as one class per ramp step and nothing else", () => {
    expect(renderBlock({ pigment: "07" }).className).toContain("week-block--area-07");
  });

  it("reaches a block with no Area as no pigment class at all", () => {
    const element = renderBlock({ pigment: null, areaName: null, origin: "frame" });

    expect(element.className).not.toMatch(/week-block--area-/);
  });

  /* PAST TWELVE AREAS THE RAMP REPEATS, and the wire carries the STEP rather than the deal, so the grid cannot tell
   * a thirteenth Area from the first. THE COLLISION IS ASSERTED RATHER THAN HIDDEN: two Areas take one pigment
   * class, and what separates them in the rendering is the NAME in the accessible label. */
  it("draws a thirteenth Area in the first step's pigment, and separates the two by name", () => {
    const first = renderBlock({ pigment: "01", areaName: "Career" });
    const thirteenth = renderBlock({ pigment: "01", areaName: "Volunteering" });

    expect(thirteenth.className).toBe(first.className);
    expect(first).toHaveAttribute("aria-label", "Leetcode · Graphs · Career");
    expect(thirteenth).toHaveAttribute("aria-label", "Leetcode · Graphs · Volunteering");
  });

  it("names the block alone where it holds no Area, rather than a trailing separator", () => {
    expect(renderBlock({ pigment: null, areaName: null, title: "Sleep" })).toHaveAttribute(
      "aria-label",
      "Sleep",
    );
  });
});

describe("the geometry a block is positioned by", () => {
  it("takes its top and height from the box the axis gave it", () => {
    const element = renderBlock({}, { topPx: 123.456789, heightPx: 26.5 });

    expect(element.style.top).toBe("123.457px");
    expect(element.style.height).toBe("26.5px");
  });

  it("insets from BOTH column edges at depth one, so its rules miss the divider", () => {
    const element = renderBlock();

    expect(element.style.left).toBe("calc(var(--grid-inset) + 0.000%)");
    expect(element.style.right).toBe("calc(var(--grid-inset) + 0.000%)");
  });

  it("keeps the inset at every overlap depth, added to the column share", () => {
    const [, second] = placeOverlaps([
      { startMin: 600, endMin: 660 },
      { startMin: 600, endMin: 660 },
    ]);
    const element = renderBlock({}, { across: second });

    expect(element.style.left).toBe("calc(var(--grid-inset) + 50.000%)");
    expect(element.style.right).toBe("calc(var(--grid-inset) + 0.000%)");
  });

  it("indents in --overlap-indent steps at depth four, rather than in a length of its own", () => {
    const spans = Array.from({ length: 4 }, (_, index) => ({
      startMin: 600 + index,
      endMin: 700,
    }));
    const element = renderBlock({}, { across: placeOverlaps(spans)[3] });

    expect(element.style.left).toBe("calc(var(--grid-inset) + 3 * var(--overlap-indent))");
    expect(element.style.zIndex).toBe("4");
  });

  it("draws a zero-length block as a zero-height box rather than dropping it", () => {
    expect(renderBlock({}, { heightPx: 0 }).style.height).toBe("0px");
  });

  it("is reachable by the keyboard at every tier, however small the pointer target", () => {
    /* Queried by ROLE rather than by reading `tabIndex`, which is 0 on any button and would pass on a disabled one.
     * What matters is that a screen reader and the tab order reach the element with its name at every height, which
     * is the claim `j` and `k` rest on: the smallest block in the week is as reachable as the largest. */
    for (const heightPx of [40, BLOCK_H_COMPACT_PX, BLOCK_H_SLIVER_PX, 4]) {
      const { container } = render(
        <Block block={gridBlock()} placement={{ ...FULL_WIDTH, heightPx }} />,
      );
      const reached = screen.getByRole("button", { name: "Leetcode · Graphs · Career" });

      expect(reached).toBe(container.firstElementChild);
      expect(reached).not.toBeDisabled();
      cleanup();
    }
  });
});

describe("the band that explains a gap", () => {
  it("draws its label where the payload carries one", () => {
    render(<ForbiddenBand heightPx={40} label="recovery · Kontron Interview" topPx={10} />);

    expect(screen.getByText("recovery · Kontron Interview")).toBeInTheDocument();
  });

  it("still draws where it carries none, because an unlabelled gap explains more than nothing", () => {
    const { container } = render(<ForbiddenBand heightPx={40} label={null} topPx={10} />);
    const band = container.querySelector(".week-band");

    expect(band).not.toBeNull();
    expect(band?.querySelector(".week-band__label")).toBeNull();
  });

  it("takes its box from the axis exactly as a block does", () => {
    const { container } = render(<ForbiddenBand heightPx={40.5} label={null} topPx={10.25} />);
    const band = container.querySelector(".week-band");

    expect(band).toHaveStyle({ top: "10.25px", height: "40.5px" });
  });

  it("draws the same element whatever the gap is, which is what makes one drawing rule true", () => {
    const window = render(<ForbiddenBand heightPx={40} label="recovery · Interview" topPx={0} />);
    const offPlan = render(<ForbiddenBand heightPx={40} label="off plan · Italy" topPx={0} />);

    expect(window.container.querySelector(".week-band")?.className).toBe(
      offPlan.container.querySelector(".week-band")?.className,
    );
  });
});

describe("the now rule", () => {
  it("is a single line at the minute it names, and says nothing to a reader", () => {
    const { container } = render(<NowRule topPx={321.5} />);
    const rule = container.firstElementChild;

    expect(rule).toHaveClass("week-now");
    expect(rule).toHaveStyle({ top: "321.5px" });
    expect(rule).toHaveAttribute("aria-hidden", "true");
  });
});
