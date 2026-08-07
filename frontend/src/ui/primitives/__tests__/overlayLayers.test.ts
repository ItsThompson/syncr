/* WHAT A DIALOG'S SCRIM MAY COVER, AND WHAT IT MAY NOT.
 *
 * FOUND IN A BROWSER AND NOT IN A TEST, which is why it is asserted from the stylesheets rather than from a
 * rendering: jsdom lays nothing out, so `getComputedStyle` on a portal'd list says nothing about what a pointer
 * would hit. The capture form's Area select rendered its list where a reader could see it and could not click it,
 * because Radix portals a select's list to the document root and the dialog's scrim covers the viewport at a
 * higher layer.
 *
 * SO THE RULE IS AN ORDERING BETWEEN TWO SHEETS. A control a dialog can contain has to float above the scrim, and
 * a select and a date field are both such controls. Reading the numbers from the files is what makes the claim
 * survive either of them moving.
 *
 * The three numbers this kit spends live in three sheets and belong in the token layer as one ladder, which is
 * ticket 1461. Until then this test is what keeps the two ends of the ordering honest. */

import { describe, expect, it } from "vitest";

import { kitStylesheet } from "../../../testing/kitStylesheets";

/** The `z-index` a rule declares, read from the sheet the browser loads. */
async function layerOf(sheet: string, selector: string): Promise<number> {
  const css = await kitStylesheet(sheet);
  const rule = new RegExp(`\\${selector}\\s*\\{([^}]*)\\}`).exec(css);
  const declared = /z-index:\s*(\d+)/.exec(rule?.[1] ?? "");
  if (declared === null) throw new Error(`${selector} in ${sheet} declares no z-index`);
  return Number(declared[1]);
}

describe("a control a dialog can contain", () => {
  it("floats above the scrim, because a list under it can be seen and not clicked", async () => {
    const scrim = await layerOf("overlay.css", ".overlay__scrim");

    expect(await layerOf("Select.css", ".select__content")).toBeGreaterThan(scrim);
    expect(await layerOf("DatePicker.css", ".date-picker__panel")).toBeGreaterThan(scrim);
  });

  /* The scrim still covers the page it dims. A ladder that lifted every popover above everything would put a
     select's list over a dialog it does not belong to, so the ordering is asserted from both ends. */
  it("leaves the scrim above the surfaces the page itself stacks", async () => {
    const scrim = await layerOf("overlay.css", ".overlay__scrim");

    expect(scrim).toBeGreaterThan(await layerOf("../domain/week-grid/grid.css", ".week-insertion"));
  });
});
