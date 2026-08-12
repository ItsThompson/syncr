/* THE RENDERED-PIXEL GATE'S PROBE, HELD AGAINST THE MARKUP THIS COMPONENT ACTUALLY EMITS.
 *
 * `scripts/check-render` is the only gate in this frontend whose input is a rendered pixel, and it reaches a browser
 * as TEXT: the class list, the data attributes and the inline style are written by hand in `page.ts`. That copy is
 * always one edit away from drifting, and a drifted probe measures a shape the product does not ship, which is worse
 * than no probe at all. Rendering the real `Block` and requiring the probe to contain everything it writes is what
 * holds the two together.
 *
 * It lives here rather than beside the script because it is a claim about what this component renders, and because a
 * script's own suite takes plain TypeScript rather than JSX. */

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  CASES,
  geometryOf,
  probePage,
  WEEK_SECTION,
} from "../../../../../scripts/check-render/page.ts";
import { WEEK_DATES, WEEK_LABELS } from "../../../../../scripts/check-render/weekColumns.ts";
import { columnLabel } from "../../../../routes/week/labels";
import { Block } from "../Block";
import { WeekGrid } from "../WeekGrid";
import type { Extent, GridBlock, WeekDay } from "../types";

const cases = geometryOf(CASES);
const modal = cases[0];
const page = probePage({ bundleName: "bundle.css", cases });

const BLOCK: GridBlock = {
  id: "b1",
  title: modal.title,
  span: { startMin: 540, endMin: 570 },
  origin: "task",
  pigment: "01",
  areaName: "Career",
  isPinned: false,
};

function realBlock(): HTMLElement {
  const { container } = render(
    <Block
      block={BLOCK}
      placement={{
        topPx: modal.cappedTopPx,
        heightPx: modal.heightPx,
        across: { left: 0, right: 0, indentSteps: 0, layer: 0, overlapCount: null, isSplit: false },
      }}
    />,
  );
  const element = container.firstElementChild;
  if (!(element instanceof HTMLElement)) throw new Error("the block rendered nothing");
  return element;
}

describe("the probe's block against this component's", () => {
  it("writes every class the component writes", () => {
    for (const className of realBlock().className.split(/\s+/)) {
      expect(page, `the probe is missing ${className}`).toContain(className);
    }
  });

  it("writes every nested element the component writes, in the same nesting", () => {
    /* NESTING, NOT JUST PRESENCE. The glyph and the title are both inside `__body`, and a probe that emitted the glyph
     * as a sibling made it a flex ITEM rather than a float, which pushed the title 17.80px down. The containment check
     * alone passed that, because every class was still present somewhere. */
    const block = realBlock();
    const body = block.querySelector(".week-block__body");

    expect(body?.querySelector(".week-block__glyph")).not.toBeNull();
    expect(body?.querySelector(".week-block__title")).not.toBeNull();
    expect(page).toContain('<span class="week-block__body"><span class="week-block__glyph"');
    for (const child of block.querySelectorAll("[class]")) {
      expect(page, `the probe is missing ${child.className}`).toContain(child.className);
    }
  });

  it("writes no shape the component does not, so the probe cannot drift by ADDING one", () => {
    const drawn = new Set(
      [...realBlock().querySelectorAll("[class]")].flatMap((child) => child.className.split(/\s+/)),
    );
    const inProbe = new Set(
      [...page.matchAll(/class="([^"]*week-block__[^"]*)"/g)].flatMap((found) =>
        found[1].split(/\s+/).filter((name) => name.startsWith("week-block__")),
      ),
    );

    for (const name of inProbe) {
      expect(drawn, `the probe draws ${name} and the component does not`).toContain(name);
    }
  });

  it("writes every attribute the component writes", () => {
    for (const name of realBlock().getAttributeNames()) {
      if (name === "style" || name === "aria-label") continue;
      expect(page, `the probe is missing ${name}`).toContain(name);
    }
  });

  it("passes the same two per-block custom values the component passes", () => {
    /* The VALUE, not just the name: `--lines` is the figure the whole gate is about, and a probe that wrote a
     * different one would measure a line count the product never sets. */
    expect(realBlock().style.getPropertyValue("--lines")).toBe(String(modal.lines));
    expect(page).toContain(`--lines:${String(modal.lines)}`);
    expect(page).toContain("var(--grid-inset)");
  });

  it("renders the same block height, so the line count under test is the product's", () => {
    expect(realBlock().style.height).toBe(`${modal.heightPx.toFixed(3)}px`);
    expect(page).toContain(`height:${modal.heightPx.toFixed(3)}px`);
  });
});

/* THE SEVEN DAY COLUMNS THE HORIZONTAL READ IS TAKEN ACROSS.
 *
 * The page's columns exist so a pointer can be over one column and outside another, which needs seven boxes a browser
 * laid out rather than one box a test invented. What holds them to the product is the same thing that holds the block:
 * the real component is rendered and the probe's markup has to be its shape.
 *
 * THE COMPARISON IS THE WHOLE SUBTREE, BY EQUALITY, so it fails on a class or an attribute REMOVED from the probe as
 * well as one added to it, and on a nesting either side changes. Attribute VALUES are excluded and their names are not:
 * both sides write `style` on a canvas, and the height in it is the page's own figure rather than the component's.
 *
 * AN EXTENT NARROWER THAN ONE QUARTER HOUR DRAWS NO GRID LINE, and a day holding nothing draws no block and no band, so
 * what the real grid renders here is exactly the frame the probe stands in for. The canvas's contents are all
 * absolutely positioned and none of them can move the box a pointer is read against, which is the only figure this
 * section of the page reports. */
const FRAME_ONLY: Extent = { startMin: 1, endMin: 14 };

function emptyDay(date: string): WeekDay {
  return {
    date,
    zone: "Europe/London",
    startMs: Date.parse(`${date}T00:00:00Z`),
    minutes: 1440,
    blocks: [],
    bands: [],
  };
}

/** One line per element: its tag, its class list, its attribute names and the text it writes itself. */
function shapeOf(root: Element, depth = 0): string[] {
  const text = [...root.childNodes]
    .filter((node) => node.nodeType === Node.TEXT_NODE)
    .map((node) => node.textContent)
    .join("");
  const attributes = root.getAttributeNames().toSorted().join(" ");
  return [
    `${"  ".repeat(depth)}${root.tagName.toLowerCase()} [${root.className}] [${attributes}] ${JSON.stringify(text)}`,
    ...[...root.children].flatMap((child) => shapeOf(child, depth + 1)),
  ];
}

function gridIn(html: string): Element {
  const holder = document.createElement("div");
  holder.innerHTML = html;
  const grid = holder.querySelector(".week-grid");
  if (grid === null) throw new Error("the markup holds no week grid");
  return grid;
}

function realGrid(): Element {
  const { container } = render(
    <WeekGrid
      days={WEEK_DATES.map(emptyDay)}
      extent={FRAME_ONLY}
      labels={WEEK_DATES.map(columnLabel)}
      nowMs={null}
      visibleHours={12}
    />,
  );
  const grid = container.querySelector(".week-grid");
  if (grid === null) throw new Error("the grid rendered nothing");
  return grid;
}

describe("the probe's seven day columns against this component's", () => {
  it("writes the same tags, classes, attributes and nesting the grid writes for seven empty days", () => {
    expect(shapeOf(gridIn(WEEK_SECTION.html))).toEqual(shapeOf(realGrid()));
  });

  it("draws one column per day of the week, which is what the boundary reads are counted across", () => {
    expect(gridIn(WEEK_SECTION.html).querySelectorAll(".week-day")).toHaveLength(WEEK_DATES.length);
    expect(realGrid().querySelectorAll(".week-day")).toHaveLength(WEEK_DATES.length);
  });

  /* The header is the shipped formatter's output for the date beside it. A script cannot call that formatter, because it
   * reaches the kit's barrel, so the strings are written out and held here instead. */
  it("heads each column with the label the week screen draws for that date", () => {
    expect(WEEK_LABELS).toEqual(WEEK_DATES.map(columnLabel));
  });

  it("puts the columns on the page, so the gate reads a section the page actually holds", () => {
    expect(page).toContain(WEEK_SECTION.html);
  });
});
