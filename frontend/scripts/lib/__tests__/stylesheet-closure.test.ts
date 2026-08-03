/* WHICH STYLESHEETS A COMPONENT LOADS, and why the intersection is the honest answer.
 *
 * The token validator resolves a `var()` reference against the sheets the importing component actually loads. Two
 * wrong models preceded it and each let a real reference through: the sheet's own declarations alone reported the
 * key hint's brackets as dangling when the browser resolves them, and every sheet in the tree passed
 * `status.css` reading a property declared inside `.gutter` in a sheet `StatusSurface` never imports.
 *
 * The fixture graph is the shape that distinguishes them: `widget.css` is loaded by two components, only one of
 * which also loads `table.css`. */

import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { filesUnder } from "../files.ts";
import { stylesheetClosures } from "../stylesheet-closure.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const closureRoot = path.join(here, "..", "__fixtures__", "closure");

const onDisk = async (candidate: string): Promise<boolean> => {
  try {
    return (await stat(candidate)).isFile();
  } catch {
    return false;
  }
};

/* `filesUnder` skips `__fixtures__`, so the fixture tree is walked directly. */
async function closures() {
  const files = [
    ...(await filesUnder(path.join(closureRoot, "widget"), [".ts", ".tsx", ".css"])),
    ...(await filesUnder(path.join(closureRoot, "shared"), [".ts", ".tsx", ".css"])),
  ];
  return stylesheetClosures({ files, exists: onDisk });
}

const named = (files: Iterable<string>): string[] =>
  [...files].map((file) => path.basename(file)).toSorted();

describe("a sheet two components load", () => {
  it("is judged against the intersection, because a reference has to resolve in both", async () => {
    const widget = (await closures()).get(path.join(closureRoot, "widget", "widget.css"));

    expect(named(widget?.importers ?? [])).toEqual(["Another.tsx", "Other.tsx", "Widget.tsx"]);
    expect(named(widget?.loadedWith ?? [])).toEqual(["base.css", "widget.css"]);
  });

  /* The intersection has to drop what only one importer loads, whichever importer is read first: `solo.css` comes
   * with `Another.tsx` alone, which is read first, and `table.css` with `Widget.tsx` alone, which is read last. */
  it("does not see a sheet only one of them loads, in either direction", async () => {
    const widget = (await closures()).get(path.join(closureRoot, "widget", "widget.css"));

    expect(named(widget?.loadedWith ?? [])).not.toContain("solo.css");
    expect(named(widget?.loadedWith ?? [])).not.toContain("table.css");
  });
});

/* THE TWO SPECIFIER SHAPES THAT ARE NOT EDGES. A bare specifier is a package, which this has no business
 * resolving, and a relative specifier that resolves to nothing is a broken module the bundler fails on rather than
 * a sheet anything loads. Both are in `Another.tsx`, so both are exercised by the closure above rather than
 * asserted in the abstract. */
describe("a specifier that is not a stylesheet edge", () => {
  it("leaves the closure alone, whether it is a package or resolves to nothing", async () => {
    const another = (await closures()).get(path.join(closureRoot, "widget", "widget.css"));

    expect(named(another?.loadedWith ?? [])).toEqual(["base.css", "widget.css"]);
  });
});

describe("a sheet one component loads", () => {
  it("sees everything that component loads with it", async () => {
    const table = (await closures()).get(path.join(closureRoot, "shared", "table.css"));

    expect(named(table?.importers ?? [])).toEqual(["Widget.tsx"]);
    expect(named(table?.loadedWith ?? [])).toEqual(["base.css", "table.css", "widget.css"]);
  });
});
describe("a CSS @import", () => {
  it("is an edge, so a sheet pulled in that way is loaded and knows what pulled it", async () => {
    const base = (await closures()).get(path.join(closureRoot, "shared", "base.css"));

    expect(named(base?.importers ?? [])).toEqual(["table.css", "widget.css"]);
    expect(named(base?.loadedWith ?? [])).toEqual(["base.css"]);
  });

  /* Two sheets in one closure reaching the same third sheet is a diamond, and the walk folds it: `Widget.tsx`
   * reaches `base.css` through its own sheet and through the table's. */
  it("is folded when two sheets in one closure reach it", async () => {
    const table = (await closures()).get(path.join(closureRoot, "shared", "table.css"));

    expect(named(table?.loadedWith ?? [])).toEqual(["base.css", "table.css", "widget.css"]);
  });
});

describe("a sheet nobody imports", () => {
  it("is loaded with nothing, which is what it would have in a browser", async () => {
    const orphan = (await closures()).get(path.join(closureRoot, "shared", "orphan.css"));

    expect(orphan?.importers).toEqual([]);
    expect(named(orphan?.loadedWith ?? [])).toEqual(["orphan.css"]);
  });
});
