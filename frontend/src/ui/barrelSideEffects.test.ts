/* WHAT IMPORTING ONE COMPONENT FROM A BARREL LOADS, READ OUT OF A BUILD.
 *
 * Both barrels state that importing one component may load another's stylesheet, and state why that is
 * accepted. The statement is worth nothing if nobody can tell whether it is still true, so it is asserted
 * against the artifact rather than against the source: one named import is compiled through the barrel, and
 * the CSS a browser would receive is searched for a family the import never asked for.
 *
 * The direction matters as much as the fact. The same import from the component's own module carries the other
 * family's selector NOWHERE, which is what makes the barrel the cause rather than the kit at large. */

import { describe, expect, it } from "vitest";

import { BARREL_PROBES, checkBarrelPayloads } from "../../scripts/check-bundle/barrels.ts";
import { buildBarrelPayloads, buildProbeStylesheet } from "../../scripts/check-bundle/build.ts";

const [domain, primitives] = BARREL_PROBES;

/* ONE build per import, shared by the file. `write: false`, so nothing reaches `dist/`. */
const throughDomainBarrel = buildProbeStylesheet(domain.barrel, domain.component);
const fromTheTableFamily = buildProbeStylesheet(domain.module, domain.component);
const throughPrimitivesBarrel = buildProbeStylesheet(primitives.barrel, primitives.component);
const payloads = buildBarrelPayloads();

describe("importing Table through the domain barrel", () => {
  it("loads the table family's own stylesheet, so the probe reached the layer at all", async () => {
    expect(await throughDomainBarrel).toContain(".table");
  });

  it.each([
    [".chart", "charts"],
    [".ledger__row", "ledger"],
    [".week-grid", "week-grid"],
  ])("loads %s, which belongs to the %s family and not to Table", async (selector) => {
    expect(await throughDomainBarrel).toContain(selector);
  });

  it("loads none of those from the table family's own module, so the barrel is the cause", async () => {
    const css = await fromTheTableFamily;

    expect(css).toContain(".table");
    expect(css).not.toContain(".chart");
    expect(css).not.toContain(".ledger__row");
    expect(css).not.toContain(".week-grid");
  });
});

describe("importing Button through the primitives barrel", () => {
  it("loads the accordion and the dialog, which a button is neither of", async () => {
    const css = await throughPrimitivesBarrel;

    expect(css).toContain(".button");
    expect(css).toContain(".accordion");
    expect(css).toContain(".dialog");
  });
});

describe("the figure the bundle gate records", () => {
  it("is a real measurement of both barrels, not a default", async () => {
    for (const payload of await payloads) {
      expect(payload.onItsOwnBytes).toBeGreaterThan(0);
      expect(payload.throughBarrelBytes).toBeGreaterThan(payload.onItsOwnBytes);
    }
  });

  it("passes its own verdict at HEAD, so the barrels' statement and the artifact agree", async () => {
    expect(checkBarrelPayloads(await payloads).findings).toEqual([]);
  });
});
