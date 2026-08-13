/* THE DETAIL PANEL BELOW --bp-wide, WHERE THE RAIL'S CONTROL IS THE ONLY ROUTE TO A REASON.
 *
 * At 1440x900 the panel has no room for a column of its own and the rail's control is what a reader has instead.
 * What these cases hold is the whole gesture rather than the state behind it: the control is reached, named,
 * activated, and the reason it exists for is READ off the panel that appears. A case asserting the open state
 * alone passes against a panel a browser never displays, which is the shape this screen shipped.
 *
 * THE PANEL LANDS BELOW THE GRID, and that is the one arrangement that leaves the grid's own width alone: the
 * panel's column is fenced to `wide:`, so below the threshold the only width reserved beside the grid is the
 * 26px rail, in both states, and a day column keeps the ledger's seventeen characters.
 *
 * jsdom APPLIES NO CSS, so the class lists the surface RENDERS are resolved through Tailwind's own compiler
 * rather than compared as text. The declaration is what a browser is handed, and the declaration is what says
 * whether the panel is displayed at this width; a class list read as a string says only that somebody wrote it. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { parse, type Container } from "postcss";

import { compileUtilities } from "../../../testing/compileTheme";
import { renderAt } from "../../../testing/renderRoute";
import {
  CHARACTER_FLOOR,
  CHARACTER_PX,
  CHROME_PX,
  layoutPixels,
} from "../../../testing/widthLedger";
import {
  LEETCODE,
  WEEK_PATH,
  buildBlock,
  buildPlan,
  buildWeekView,
  installWeekReads,
  monday,
} from "./fixtures";
import { WIDE_MIN_WIDTH_PX } from "../panelRoom";

/** The display the ticket names: the widest one with no room for the panel's own column. */
const VIEWPORT = { widthPx: 1440, heightPx: 900 };

const JSDOM_VIEWPORT = { widthPx: window.innerWidth, heightPx: window.innerHeight };

afterEach(() => {
  window.innerWidth = JSDOM_VIEWPORT.widthPx;
  window.innerHeight = JSDOM_VIEWPORT.heightPx;
});

const OPEN_THE_PANEL = "Open the detail panel";
const CLOSE_TO_THE_RAIL = "Close the detail panel to its rail";

/** The week as this suite reads it: one block carrying a reason with something in it to reach. */
function weekWithAReason() {
  return buildWeekView({
    live: buildPlan({
      blocks: [
        buildBlock({
          reason: {
            clauses: [
              {
                kind: "instead_of",
                placement: { start: monday("13:00"), end: monday("14:30") },
                objectiveDelta: 0.18,
              },
            ],
          },
        }),
      ],
    }),
  });
}

async function renderWeekAt(widthPx: number): Promise<void> {
  window.innerWidth = widthPx;
  window.innerHeight = VIEWPORT.heightPx;
  installWeekReads(weekWithAReason());
  renderAt(WEEK_PATH);
  await screen.findByLabelText(`${LEETCODE} · Career`);
}

const railOpens = (): HTMLElement => screen.getByRole("button", { name: OPEN_THE_PANEL });
const railCloses = (): HTMLElement => screen.getByRole("button", { name: CLOSE_TO_THE_RAIL });

/**
 * The panel, opened the way a reader below the threshold has to open it.
 *
 * Two gestures rather than one, and both are the screen's: `j` moves the cursor onto a block without asking why
 * it is there, and the rail's control is what asks. A pointer press on the block itself opens the panel as well,
 * which is a different route to the same state and is held by this screen's other suites.
 */
async function openFromTheRail(): Promise<HTMLElement> {
  await userEvent.keyboard("j");
  await userEvent.click(railOpens());
  return screen.findByLabelText("Detail");
}

function grid(): Element {
  const found = document.querySelector(".week-grid");
  if (found === null) throw new Error("the week grid is not rendered");
  return found;
}

/** The column an element the surface laid out sits in, which is what carries its width. */
function columnOf(element: HTMLElement): HTMLElement {
  if (element.parentElement === null) throw new Error("the element has no column");
  return element.parentElement;
}

/** The element the surface publishes its open state on, which is the surface's own root. */
function surface(): HTMLElement {
  const found = document.querySelector<HTMLElement>("[data-panel]");
  if (found === null) throw new Error("no element carries data-panel");
  return found;
}

interface Declared {
  readonly property: string;
  readonly value: string;
  /** The media query the declaration sits inside, or null where it applies at every width. */
  readonly media: string | null;
}

/**
 * What a browser is handed for a class list, as declarations, with the width each one is fenced to.
 *
 * The utilities layer only. The preflight and the theme's own `:root` blocks are compiled into every answer, and
 * counting them would let a claim about a class list be satisfied by a declaration no class in it produced.
 */
async function declarationsFor(classList: string): Promise<Declared[]> {
  const candidates = classList.split(/\s+/).filter((name) => name !== "");
  const found: Declared[] = [];
  parse(await compileUtilities(candidates)).walkAtRules("layer", (layer) => {
    if (layer.params !== "utilities") return;
    collect(layer, null, found);
  });
  return found;
}

/** Every declaration under a container, carrying the media query it was found inside. */
function collect(container: Container, media: string | null, into: Declared[]): void {
  for (const node of container.nodes ?? []) {
    if (node.type === "decl") into.push({ property: node.prop, value: node.value, media });
    if (node.type === "rule") collect(node, media, into);
    if (node.type === "atrule") collect(node, node.name === "media" ? node.params : media, into);
  }
}

const atEveryWidth = (declared: Declared): boolean => declared.media === null;
const aboveTheThreshold = (declared: Declared): boolean =>
  declared.media === `(width >= ${WIDE_MIN_WIDTH_PX}px)`;
const propertyIs =
  (property: string) =>
  (declared: Declared): boolean =>
    declared.property === property;

describe("the rail's control at 1440x900", () => {
  it("is reached by Tab and states what it opens, so the panel is not pointer-only", async () => {
    await renderWeekAt(VIEWPORT.widthPx);
    const control = railOpens();

    /* WALKED RATHER THAN FOCUSED. `control.focus()` asserts that an element can be made to hold focus, which
     * every element can; what a keyboard reader needs is that the tab order arrives at it. */
    let stops = 0;
    while (document.activeElement !== control && stops < 60) {
      // oxlint-disable-next-line no-await-in-loop -- a traversal is one stop at a time: tabs in parallel are not one
      await userEvent.tab();
      stops += 1;
    }

    expect(document.activeElement).toBe(control);
    expect(control).toHaveAccessibleName(OPEN_THE_PANEL);
  });

  it("mounts the panel on a pointer press, with the block's reason readable", async () => {
    await renderWeekAt(VIEWPORT.widthPx);
    await userEvent.keyboard("j");
    /* A CURSOR MOVE ALONE LEAVES IT CLOSED at this width, which is what makes the control the reader's route. */
    expect(screen.queryByLabelText("Detail")).not.toBeInTheDocument();

    await userEvent.click(railOpens());

    const reason = await screen.findByLabelText("Reason");
    expect(within(reason).getByText("instead of")).toBeInTheDocument();
    expect(
      within(reason).getByText("Mon 13:00 to 14:30 · what the solver proposed"),
    ).toBeInTheDocument();
  });

  it("mounts it from the keyboard, on the key a button answers to", async () => {
    await renderWeekAt(VIEWPORT.widthPx);
    await userEvent.keyboard("j");
    railOpens().focus();

    await userEvent.keyboard(" ");

    expect(await screen.findByLabelText("Detail")).toBeInTheDocument();
  });

  it("is not the only keyboard route: Enter on a selected block opens it too", async () => {
    await renderWeekAt(VIEWPORT.widthPx);
    await userEvent.keyboard("j");
    expect(screen.queryByLabelText("Detail")).not.toBeInTheDocument();

    await userEvent.keyboard("{Enter}");

    expect(await screen.findByLabelText("Detail")).toBeInTheDocument();
  });
});

describe("where the panel lands below --bp-wide", () => {
  it("is displayed at 1440 rather than fenced to a width this display does not have", async () => {
    await renderWeekAt(VIEWPORT.widthPx);
    const panel = await openFromTheRail();

    const declared = await declarationsFor(columnOf(panel).className);

    expect(declared.filter(atEveryWidth).filter(propertyIs("display"))).toEqual([]);
  });

  it("stacks under the grid below the threshold and sits beside it above, one declaration each", async () => {
    await renderWeekAt(VIEWPORT.widthPx);
    await openFromTheRail();

    const declared = (await declarationsFor(surface().className)).filter(
      propertyIs("flex-direction"),
    );

    expect(declared.filter(atEveryWidth).map((each) => each.value)).toEqual(["column"]);
    expect(declared.filter(aboveTheThreshold).map((each) => each.value)).toEqual(["row"]);
  });

  it("follows the grid in the document, so the reveal inserts nothing above the reader's place", async () => {
    await renderWeekAt(VIEWPORT.widthPx);
    const panel = await openFromTheRail();

    const order = grid().compareDocumentPosition(columnOf(panel));

    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(order & Node.DOCUMENT_POSITION_PRECEDING).toBe(0);
  });

  /* THE LEDGER RATHER THAN A TABLE OF PIXELS. What makes the two states one width is that the panel reserves
   * nothing beside the grid at this viewport, so the reserved widths are collected from the surface's own
   * columns in each state and compared; the arithmetic that follows is the width policy's own. */
  it("reserves only the 26px rail beside the grid in both states, so a day column still holds 17 characters", async () => {
    await renderWeekAt(VIEWPORT.widthPx);
    const closed = await reservedBesideTheGrid([columnOf(railOpens())]);

    const panel = await openFromTheRail();
    const open = await reservedBesideTheGrid([columnOf(railCloses()), columnOf(panel)]);

    expect(closed).toEqual(["var(--w-detail-closed)"]);
    expect(open).toEqual(closed);

    const gridPx =
      VIEWPORT.widthPx -
      (await layoutPixels("--w-sidebar")) -
      (await layoutPixels("--w-detail-closed"));

    expect(Math.floor(gridPx / 7)).toBeGreaterThanOrEqual(
      Math.floor(CHARACTER_FLOOR * CHARACTER_PX + CHROME_PX),
    );
  });

  it("transitions nothing, in any of the three class lists the arrangement rests on", async () => {
    await renderWeekAt(VIEWPORT.widthPx);
    const panel = await openFromTheRail();

    const declared = [
      ...(await declarationsFor(surface().className)),
      ...(await declarationsFor(columnOf(railCloses()).className)),
      ...(await declarationsFor(columnOf(panel).className)),
    ];

    expect(declared.filter((each) => /transition|animation|duration/.test(each.property))).toEqual(
      [],
    );
  });
});

/** Every width the given columns reserve at this viewport, which is what the grid does not get. */
async function reservedBesideTheGrid(columns: readonly HTMLElement[]): Promise<string[]> {
  const declared = await Promise.all(
    columns.map(async (column) => declarationsFor(column.className)),
  );
  return declared
    .flat()
    .filter(atEveryWidth)
    .filter(propertyIs("width"))
    .map((each) => each.value);
}

/* THE REVEAL MOVES NOTHING UNDER THE READER, and it is where the panel MOUNTS that delivers that rather than a scroll
 * correction: the panel is inserted after the control that reveals it, so nothing the reader is looking at above it can
 * be displaced. jsdom has no layout, so what is asserted here is the document order the property rests on; the
 * displacement itself is a composed figure and belongs to a browser.
 *
 * The one case where the control does move is a reader scrolled to the foot of the document, where closing shortens it
 * and the scroll position is clamped. That displacement cannot be corrected by scrolling, because the correction would
 * have to scroll past the end of the shortened document. */
describe("the reveal under a reader", () => {
  it("inserts the panel after the control that reveals it, so nothing above it is displaced", async () => {
    await renderWeekAt(VIEWPORT.widthPx);
    const control = railOpens();
    const panel = await openFromTheRail();

    const order = control.compareDocumentPosition(columnOf(panel));

    expect(order & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(order & Node.DOCUMENT_POSITION_PRECEDING).toBe(0);
  });

  it("adds one element to the surface and nothing else, so the reveal is the panel alone", async () => {
    await renderWeekAt(VIEWPORT.widthPx);
    const before = surface().children.length;

    await openFromTheRail();

    expect(surface().children.length).toBe(before + 1);
    expect(surface().lastElementChild).toBe(columnOf(screen.getByLabelText("Detail")));
  });
});
