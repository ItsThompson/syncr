/* THE TWELVE BINDINGS, EACH DRIVEN BY ITS OWN KEYSTROKE.
 *
 * WHAT THIS ANSWERS THAT `selection.test.ts` CANNOT. That file proves the traversal as arithmetic, calling it with `1`
 * and `-1`; it says nothing about whether `j` is wired to `+1`, whether `l` is the NEXT column, or whether `[` is the
 * PREVIOUS week. A binding wired to the wrong direction, or never registered at all, stays green there. That is the
 * same class as the defect this ticket had to close in `useScreenChords`: a key that fires the wrong action.
 *
 * `j` IS NEXT AND `k` IS PREVIOUS, which is the vi convention and is stated here because section 15's table reads
 * "`j` `k` | Previous and next block" in that order. The reader's own muscle memory is what settles it: `j` moves down
 * a list everywhere else they type, and the grid's list runs down the day.
 *
 * SELECTION IS OBSERVED THROUGH `data-selected` AND FOCUS, which is what the reader sees, rather than through the
 * hook's own state. A week is observed through the band's own reading, because a week is a URL in this product.
 *
 * `Shift+Up`, `Shift+Down`, `p` and `Shift+A` are driven in `pinning.test.tsx` and `panels.test.tsx`, where the
 * request each makes is the observable. This file covers the nine that move something on the screen. */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { renderAt } from "../../../testing/renderRoute";
import { todayIn } from "../../../lib/zonedInstant";
import { isoWeekOf } from "../../today/isoWeek";
import { WIDE_MIN_WIDTH_PX } from "../panelRoom";
import {
  APPLICATION,
  BLOCK_APPLICATION,
  BLOCK_GYM,
  GYM,
  ISO_WEEK,
  LEETCODE,
  WEEK_PATH,
  ZONE,
  buildBlock,
  buildPlan,
  buildWeekView,
  installWeekReads,
  monday,
  tuesday,
} from "./fixtures";

/* Monday holds two blocks and Tuesday one, so `j` has somewhere to go and `l` has a column to reach. The payload's
 * order is not the time order, so a traversal that walked the array would land wrongly. */
const TWO_ON_MONDAY = buildPlan({
  blocks: [
    buildBlock({
      id: BLOCK_GYM,
      title: GYM,
      interval: { start: monday("18:00"), end: monday("19:00") },
    }),
    buildBlock(),
    buildBlock({
      id: BLOCK_APPLICATION,
      title: APPLICATION,
      interval: { start: tuesday("19:00"), end: tuesday("19:30") },
    }),
  ],
});

async function renderWeek() {
  const reads = installWeekReads(buildWeekView({ live: TWO_ON_MONDAY }));
  renderAt(WEEK_PATH);
  await screen.findByLabelText(`${LEETCODE} · Career`);
  return reads;
}

/* THE WIDTH IS SET RATHER THAN INHERITED. The panel opens unasked where there is room for its own column, so a case
 * about `Enter` has to state which side of that threshold it renders on: at jsdom's own width the premise would be a
 * default nobody wrote down. Restored after each case, so a narrow render does not leave the next one narrow. */
const JSDOM_WIDTH = window.innerWidth;

afterEach(() => {
  window.innerWidth = JSDOM_WIDTH;
});

function blockOf(title: string): HTMLElement {
  return screen.getByLabelText(`${title} · Career`);
}

/** What the band's eyebrow says, which is where the week on screen is readable. */
function bandReading(): string {
  return screen.getAllByText(/\d{4}-W\d{2}/)[0].textContent ?? "";
}

function selectedTitles(): string[] {
  return [...document.querySelectorAll("[data-selected]")].map(
    (element) => element.getAttribute("aria-label") ?? "",
  );
}

describe("j and k, between blocks in the current column", () => {
  it("j selects the first block of the week from nothing, then the next one in time order", async () => {
    await renderWeek();

    await userEvent.keyboard("j");

    expect(blockOf(LEETCODE)).toHaveAttribute("data-selected");
    /* SELECTION MOVES FOCUS, which is what makes a sliver-tier block reachable: the ring is the kit's own. */
    expect(blockOf(LEETCODE)).toHaveFocus();

    await userEvent.keyboard("j");

    expect(blockOf(GYM)).toHaveAttribute("data-selected");
    expect(selectedTitles()).toHaveLength(1);
  });

  it("k goes back up, and holds at the first block rather than clearing", async () => {
    await renderWeek();
    await userEvent.keyboard("jj");
    expect(blockOf(GYM)).toHaveAttribute("data-selected");

    await userEvent.keyboard("k");
    expect(blockOf(LEETCODE)).toHaveAttribute("data-selected");

    await userEvent.keyboard("k");
    expect(blockOf(LEETCODE)).toHaveAttribute("data-selected");
  });
});

describe("h and l, between day columns", () => {
  it("l reaches the next column, preserving the nearest block in time", async () => {
    await renderWeek();
    await userEvent.keyboard("j");

    await userEvent.keyboard("l");

    expect(blockOf(APPLICATION)).toHaveAttribute("data-selected");
    expect(selectedTitles()).toHaveLength(1);
  });

  it("h goes back, and holds at the first column", async () => {
    await renderWeek();
    await userEvent.keyboard("jl");
    expect(blockOf(APPLICATION)).toHaveAttribute("data-selected");

    await userEvent.keyboard("h");
    /* Tuesday's 19:00 block is nearest Monday's 18:00 one, not the 09:00 one the traversal started at. */
    expect(blockOf(GYM)).toHaveAttribute("data-selected");

    await userEvent.keyboard("h");
    expect(blockOf(GYM)).toHaveAttribute("data-selected");
  });
});

describe("the keys that change the week", () => {
  it("] moves to the next week and [ back to the previous one", async () => {
    const reads = await renderWeek();
    expect(bandReading()).toContain(ISO_WEEK);

    await userEvent.keyboard("]");

    await waitFor(() => expect(bandReading()).toContain("2026-W08"));

    /* `[` is a descriptor character in userEvent's own keyboard language, so it is escaped rather than typed. */
    await userEvent.keyboard("{[}");
    await waitFor(() => expect(bandReading()).toContain(ISO_WEEK));

    await userEvent.keyboard("{[}");
    await waitFor(() => expect(bandReading()).toContain("2026-W06"));

    /* The reading is what a reader sees; the request is what the api was asked for. Both, because a band that read a
     * URL parameter without the screen reading the week would be a navigation that fetched nothing. The SET rather
     * than the sequence: coming back to a week already in the cache issues no second request, which is the point of
     * keying by week, and how many times a fresh key is fetched is SWR's business rather than this screen's. */
    expect(new Set(reads.weeksRead())).toEqual(new Set([ISO_WEEK, "2026-W08", "2026-W06"]));
  });

  /* `T` MOVES TO THE WEEK HOLDING TODAY, so the expectation is computed the way the screen computes it rather than
   * hard-coded: a literal week would pass this week and fail next. The zone is the fixture's, which is what the
   * screen resolves today in. */
  it("T moves to the week holding today", async () => {
    const reads = await renderWeek();
    const thisWeek = isoWeekOf(todayIn(ZONE, Date.now()));

    await userEvent.keyboard("T");

    await waitFor(() => expect(bandReading()).toContain(thisWeek ?? "never"));
    expect(reads.weeksRead().at(-1)).toBe(thisWeek);
  });
});

/** The one level the band's segment marks as drawn, which is where a cycled level becomes visible. */
function pickedLevel(): string | undefined {
  return (
    document.querySelector('fieldset[aria-label="Visible hours"] [aria-pressed="true"]')
      ?.textContent ?? undefined
  );
}

describe("z cycles the visible hours", () => {
  it("moves to the next available level and marks it in the band's segment", async () => {
    await renderWeek();
    expect(pickedLevel()).toBe("12h");

    await userEvent.keyboard("z");

    /* The walk is hourly through the levels this display can draw, and the fixture's stored 12 has every level to
     * the cap 16 available, so one press lands on the next hour rather than on a ladder rung. */
    expect(pickedLevel()).toBe("13h");
  });
});

describe("Enter and Escape", () => {
  /* THE ONE CASE THAT CAN TELL WHETHER `Enter` IS BOUND AT ALL, and the premise is the reason it is written this way. A
   * selected block HOLDS FOCUS and a block is a real button, and `useKeyBinding` calls `preventDefault()` on a match, so
   * the two routes are mutually exclusive and land on the same observable: with the binding the document handler runs and
   * suppresses the button's click, without it the click reaches `onSelect`, which also opens the panel. With focus off
   * the block -- a reader who selected with the keys and then clicked the page -- the binding is the only route left.
   * Both halves of the premise are asserted rather than assumed, so this case fails loudly instead of going quiet if a
   * later change moves focus back onto an element its own activation would open the panel from. */
  it("Enter opens the detail panel for the selected block, with focus off the block itself", async () => {
    window.innerWidth = WIDE_MIN_WIDTH_PX - 1;
    await renderWeek();
    await userEvent.keyboard("j");
    blockOf(LEETCODE).blur();
    expect(document.body).toHaveFocus();
    expect(screen.queryByLabelText("Detail")).not.toBeInTheDocument();

    await userEvent.keyboard("{Enter}");

    const detail = await screen.findByLabelText("Detail");
    expect(within(detail).getByText(LEETCODE)).toBeInTheDocument();
  });

  /* THE OTHER EDGE, at the width where the panel is open already: `Enter` on the focused block is the block's own
   * activation, which is the pointer's route, and neither route toggles. Both openers SET the state. */
  it("activating the selected block again holds the panel open rather than toggling it shut", async () => {
    window.innerWidth = WIDE_MIN_WIDTH_PX;
    await renderWeek();
    await userEvent.keyboard("j");
    await screen.findByLabelText("Detail");

    await userEvent.keyboard("{Enter}");

    expect(screen.getByLabelText("Detail")).toBeInTheDocument();
    expect(blockOf(LEETCODE)).toHaveAttribute("data-selected");
  });

  it("Enter with nothing selected opens nothing", async () => {
    window.innerWidth = WIDE_MIN_WIDTH_PX - 1;
    await renderWeek();

    await userEvent.keyboard("{Enter}");

    expect(screen.queryByLabelText("Detail")).not.toBeInTheDocument();
  });

  it("Escape clears the selection and closes the panel", async () => {
    window.innerWidth = WIDE_MIN_WIDTH_PX;
    await renderWeek();
    await userEvent.keyboard("j");
    await screen.findByLabelText("Detail");

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByLabelText("Detail")).not.toBeInTheDocument();
    expect(selectedTitles()).toEqual([]);
  });
});
