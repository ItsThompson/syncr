/* THE TRUNCATION REFUSAL, ARMED OVER EVERY KIT FAMILY.
 *
 * A label that ends in an ellipsis is a label the reader cannot read, and identity-bearing text is exactly the
 * text whose absence a screen silently becomes wrong about. The week-grid family asserts its own refusal in
 * `blockStylesheet.test.ts`; this is the same question asked of the whole kit, so the refusal does not depend on
 * which family a truncating rule first ships in.
 *
 * The sweep reads DECLARATIONS over every stylesheet in `ui/primitives`, `ui/layout` and `ui/domain`, by
 * property name, so no value or vendor spelling slips past it. It is bounded as an inventory rather than as a
 * blacklist: the exact set of (sheet, selector, property) triples the kit may declare, so an exception that
 * grows a second property, a fourth exception, and a kit that stops excusing one all fail here.
 *
 * THE EXCUSES ARE NAMED AND EACH CARRIES ITS REASON:
 *
 *   `.meter` draws block characters in a fixed-width run; nothing it renders is a name
 *   `.key-hint` renders one keyboard glyph between brackets; nothing it renders is a name
 *   `.verdict-panel__recovers` renders a tabular figure; nothing it renders is a name
 *
 * None of the three draws identity-bearing text, so nowrap costs the reader nothing. A selector that starts to
 * carry a title through one of these classes is a change to this list, not a quiet pass. */

import { beforeAll, describe, expect, it } from "vitest";

import { domainDir, layoutDir, primitivesDir } from "../testing/kitStylesheets";
import { truncationDeclarations } from "../testing/layerRules";

const KIT_DIRECTORIES = [primitivesDir, layoutDir, domainDir];

/* The three layers are read once and both assertions answer from that one read. */
let spent: string[];
let values: string[];

beforeAll(async () => {
  const perLayer = await Promise.all(KIT_DIRECTORIES.map((dir) => truncationDeclarations(dir)));
  spent = perLayer
    .flat()
    .map(({ sheet, selector, property }) => `${sheet} ${selector} -> ${property}`)
    .toSorted();
  values = perLayer
    .flat()
    .map(({ property, value }) => `${property}: ${value}`)
    .toSorted();
});

describe("no family in the kit truncates", () => {
  it("declares a truncation property on exactly the three excused selectors", () => {
    expect(spent).toEqual([
      /* The meter's cells butt against each other, so a wrapped run would read as two meters. */
      "charts/charts.css .meter -> white-space",
      /* One bracketed glyph, never prose. */
      "marks/marks.css .key-hint -> white-space",
      /* A tabular figure beside the statement it qualifies. */
      "verdict-panel/verdict.css .verdict-panel__recovers -> white-space",
    ]);
  });

  it("excuses only nowrap, so an exception cannot grow an ellipsis or a clamp", () => {
    expect(values).toEqual(["white-space: nowrap", "white-space: nowrap", "white-space: nowrap"]);
  });
});
