/* WHAT IMPORTING ONE COMPONENT FROM A BARREL LOADS, READ OUT OF A BUILD.
 *
 * Both barrels state that importing one component may load another's stylesheet, and state why that is
 * accepted. The statement is worth nothing if nobody can tell whether it is still true, so it is asserted
 * against the artifact rather than against the source: one named import is compiled through the barrel, and
 * the CSS a browser would receive is searched for a family the import never asked for.
 *
 * The direction matters as much as the fact. The same import from the component's own module carries the other
 * family's selector NOWHERE, which is what makes the barrel the cause rather than the kit at large.
 *
 * The domain barrel accepts the side effect on one further ground: every family is rendered by at least one
 * route, so none of the CSS is bytes a session never uses. That clause can go false with no stylesheet
 * changing, and the sibling layer proves it is not a theoretical worry, since `ui/primitives` exports two
 * controls no screen renders and ships their sheets. So the clause is measured here too. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { BARREL_PROBES, checkBarrelPayloads } from "../../scripts/check-bundle/barrels.ts";
import { buildBarrelPayloads, buildProbeStylesheet } from "../../scripts/check-bundle/build.ts";
import { blankJsComments } from "../../scripts/lib/comments.ts";
import { filesUnder } from "../../scripts/lib/files.ts";
import { appSourceDir } from "../../scripts/lib/paths.ts";
import { componentNamesIn } from "../testing/kitExports.ts";

const [domain, primitives] = BARREL_PROBES;

/* ONE build per import, shared by the file. `write: false`, so nothing reaches `dist/`. */
const throughDomainBarrel = buildProbeStylesheet(domain.barrel, domain.component);
const fromTheTableFamily = buildProbeStylesheet(domain.module, domain.component);
const throughPrimitivesBarrel = buildProbeStylesheet(primitives.barrel, primitives.component);
const payloads = buildBarrelPayloads();

/* The families as the barrel reaches them, from the tree rather than from a list beside it: a family added to
 * the directory and to the barrel is judged below without being named here. */
const FAMILIES: Record<string, Record<string, unknown>> = import.meta.glob("./domain/*/index.ts", {
  eager: true,
});

function familyOf(globKey: string): string {
  return globKey.split("/")[2];
}

/* Where a family is rendered: the screens, and the shell the screens hang inside. Tests are excluded, because
 * a test mounting a component is not a route rendering it, and that is the whole distinction the clause makes.
 * Comments are blanked, since a family named in prose is not a rendering either. */
const consumerSources = (async () => {
  const perDirectory = await Promise.all(
    ["routes", "app"].map((directory) =>
      filesUnder(path.join(appSourceDir, directory), [".ts", ".tsx"]),
    ),
  );
  const consumers = perDirectory.flat().filter((file) => !file.includes(".test."));
  return Promise.all(consumers.map(async (file) => blankJsComments(await readFile(file, "utf8"))));
})();

/* An exported name is an identifier, so the word boundary is the whole of the match. A name search rather than
 * a resolved import is the only instrument available: a screen imports `Table` from the barrel and never names
 * the family it came from, so the re-export is where family attribution is lost. */
function namesIn(source: string, name: string): boolean {
  return new RegExp(`\\b${name}\\b`).test(source);
}

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

  /* THE REFUSAL, THROUGH A REAL BUILD RATHER THAN A SYNTHETIC FIGURE. `month.ts` is date arithmetic and imports
   * no stylesheet, so a probe pointed at it produces the shape a probe pointed at the wrong module would: a
   * figure of zero, which reads as the largest saving this gate could possibly report. */
  it("refuses a probe whose module emits no stylesheet, rather than printing zero as a saving", async () => {
    const measured = await buildBarrelPayloads([
      {
        barrel: primitives.barrel,
        component: "monthGrid",
        module: path.join(path.dirname(primitives.module), "month.ts"),
      },
    ]);

    expect(measured[0]?.throughBarrelBytes).toBeGreaterThan(0);
    expect(measured[0]?.onItsOwnBytes).toBe(0);
    expect(checkBarrelPayloads(measured).findings.map((finding) => finding.check)).toEqual([
      "barrel-payload-unmeasured",
    ]);
  });
});

describe("the route clause the domain barrel's acceptance rests on", () => {
  it("judges every family directory, so one the glob stopped matching is visible", async () => {
    const directories = (
      await readdir(path.join(appSourceDir, "ui", "domain"), { withFileTypes: true })
    )
      .filter((entry) => entry.isDirectory() && entry.name !== "__tests__")
      .map((entry) => entry.name);

    expect(Object.keys(FAMILIES).map(familyOf).toSorted()).toEqual(directories.toSorted());
  });

  it("reads the screens and the shell, so the cases below judge a real set", async () => {
    expect((await consumerSources).length).toBeGreaterThan(20);
  });

  it.each(Object.keys(FAMILIES))("%s is rendered by at least one route", async (key) => {
    const names = componentNamesIn(FAMILIES[key]);
    const sources = await consumerSources;

    expect(names).not.toEqual([]);
    expect(names.filter((name) => sources.some((source) => namesIn(source, name)))).not.toEqual([]);
  });

  /* THE SEARCH'S OWN CONTROL. An empty result is the failing answer above, and an empty result is also what a
   * search that had stopped matching would give. `Accordion` is exported by the primitives barrel and named by
   * no screen, which is exactly the shape this search has to be able to report. */
  it("reports no route naming Accordion, which is the shape it must be able to report", async () => {
    const sources = await consumerSources;

    expect(sources.some((source) => namesIn(source, "Accordion"))).toBe(false);
  });
});
