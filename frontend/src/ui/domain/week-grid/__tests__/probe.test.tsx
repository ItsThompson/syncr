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
  LINES_SECTION,
  probePage,
  WEEK_SECTION,
  type CaseGeometry,
} from "../../../../../scripts/check-render/page.ts";
import { LINE_EXTENT } from "../../../../../scripts/check-render/lineWeight.ts";
import { WEEK_DATES, WEEK_LABELS } from "../../../../../scripts/check-render/weekColumns.ts";
import { columnLabel } from "../../../../routes/week/labels";
import { Block, type BlockStates } from "../Block";
import { WeekGrid } from "../WeekGrid";
import type { Extent, GridBlock, WeekDay } from "../types";

const cases = geometryOf(CASES);
const modal = cases[0];
const page = probePage({ bundleName: "bundle.css", cases });

/** The block one case stands for: its title, its origin, and the glyph slot's pinned claim. */
function blockFixture(each: CaseGeometry): GridBlock {
  return {
    id: "b1",
    title: each.title,
    span: { startMin: 540, endMin: 570 },
    origin: each.origin ?? "task",
    pigment: "01",
    areaName: "Career",
    isPinned: each.glyph === "pinned",
  };
}

/** The case's states in `BlockStates`' own spelling. Split is a placement fact and travels separately. */
function statesOf(each: CaseGeometry): BlockStates {
  return {
    isSelected: each.states?.selected === true ? true : undefined,
    isConflicted: each.states?.conflicted === true ? true : undefined,
    isProposalTarget: each.states?.proposalTarget === true ? true : undefined,
  };
}

function realBlock(each: CaseGeometry): HTMLElement {
  const rendered = render(
    <Block
      block={blockFixture(each)}
      placement={{
        topPx: each.cappedTopPx,
        heightPx: each.heightPx,
        across: {
          left: 0,
          right: 0,
          indentSteps: 0,
          layer: 0,
          overlapCount: null,
          isSplit: each.states?.split === true,
        },
      }}
      states={statesOf(each)}
    />,
  );
  const element = rendered.container.firstElementChild;
  rendered.unmount();
  if (!(element instanceof HTMLElement)) throw new Error("the block rendered nothing");
  return element;
}

describe("the probe's blocks against this component's", () => {
  it("writes every class every case's rendering writes", () => {
    for (const each of cases) {
      for (const className of realBlock(each).className.split(/\s+/)) {
        expect(page, `${each.name}: the probe is missing ${className}`).toContain(className);
      }
    }
  });

  it("writes every nested element every case writes, in the same nesting", () => {
    /* NESTING, NOT JUST PRESENCE. The glyph and the title are both inside `__body`, and a probe that emitted the glyph
     * as a sibling made it a flex ITEM rather than a float, which pushed the title 17.80px down. The containment check
     * alone passed that, because every class was still present somewhere. The anchor's hatch sits before `__body`,
     * which is where the component puts it, so the same containment catches a hatch moved out of order. */
    const body = realBlock(modal).querySelector(".week-block__body");

    expect(body?.querySelector(".week-block__glyph")).not.toBeNull();
    expect(body?.querySelector(".week-block__title")).not.toBeNull();
    expect(page).toContain('<span class="week-block__body"><span class="week-block__glyph"');
    for (const each of cases) {
      for (const child of realBlock(each).querySelectorAll("[class]")) {
        expect(page, `${each.name}: the probe is missing ${child.className}`).toContain(
          child.className,
        );
      }
    }
  });

  it("writes no shape the components do not, so the probe cannot drift by ADDING one", () => {
    const drawn = new Set(
      cases.flatMap((each) =>
        [...realBlock(each).querySelectorAll("[class]")].flatMap((child) =>
          child.className.split(/\s+/),
        ),
      ),
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

  it("writes every attribute every case's rendering writes", () => {
    for (const each of cases) {
      for (const name of realBlock(each).getAttributeNames()) {
        if (name === "style" || name === "aria-label") continue;
        expect(page, `${each.name}: the probe is missing ${name}`).toContain(name);
      }
    }
  });

  it("passes the same two per-block custom values the component passes", () => {
    /* The VALUE, not just the name: `--lines` is the figure the whole gate is about, and a probe that wrote a
     * different one would measure a line count the product never sets. */
    expect(realBlock(modal).style.getPropertyValue("--lines")).toBe(String(modal.lines));
    expect(page).toContain(`--lines:${String(modal.lines)}`);
    expect(page).toContain("var(--grid-inset)");
  });

  it("renders every case at the height the geometry says, so the line count under test is the product's", () => {
    for (const each of cases) {
      /* The block rounds to three decimals and the CSSOM trims a trailing zero, so both sides are read back as the
       * same rounded number rather than as one literal string. */
      expect(Number.parseFloat(realBlock(each).style.height)).toBe(
        Number(each.heightPx.toFixed(3)),
      );
      expect(page).toContain(`height:${each.heightPx.toFixed(3)}px`);
    }
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

/* THE LINE-WEIGHT SECTION AGAINST THE COMPONENT.
 *
 * The gate reads whether `[data-dragging]` steps the quarter lines to hour weight off one canvas of grid lines that
 * this markup carries. What holds it to the product is the same move as the block and the columns: the real
 * `WeekGrid` renders over the same slice of the axis, and the section has to draw the same lines with the same
 * classes. The section ships AT REST; its reading script puts the attribute on the grid itself, so a section parked
 * permanently mid-drag cannot measure anything the flip does not. */
describe("the line-weight section against this component's", () => {
  function gridOverTheSlice(): Element {
    const { container } = render(
      <WeekGrid
        days={WEEK_DATES.map(emptyDay)}
        extent={{ ...LINE_EXTENT }}
        labels={WEEK_DATES.map(columnLabel)}
        nowMs={null}
        visibleHours={12}
      />,
    );
    const grid = container.querySelector(".week-grid");
    if (grid === null) throw new Error("the grid rendered nothing");
    return grid;
  }

  it("draws the same lines one canvas of the real grid draws over the same slice of the axis", () => {
    const real = [...(gridOverTheSlice().querySelector(".week-day__canvas")?.children ?? [])].map(
      (line) => line.className,
    );
    const probed = [...gridIn(LINES_SECTION.html).querySelectorAll(".week-grid__line")].map(
      (line) => line.className,
    );

    expect(real.length).toBeGreaterThan(0);
    expect(probed).toEqual(real);
  });

  it("ships at rest and lets its reading step it to dragging", () => {
    expect(gridIn(LINES_SECTION.html).getAttribute("data-dragging")).toBeNull();
    expect(LINES_SECTION.script).toContain('setAttribute("data-dragging"');
  });
});
