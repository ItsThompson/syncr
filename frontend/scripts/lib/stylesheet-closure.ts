/* WHICH STYLESHEETS A COMPONENT ACTUALLY LOADS.
 *
 * A `var()` reference in a component sheet has to resolve in the browser, and what the browser has loaded is
 * whatever the module that imported that sheet pulled in with it. Neither of the two obvious models is that:
 *
 *   the sheet's OWN declarations alone is too narrow. The kit's glyph table is declared in
 *   `ui/primitives/glyphs.css` and a domain component's key hint legitimately draws its brackets from it, so the
 *   narrow model reported a reference the browser resolves
 *
 *   every sheet in the tree is too wide, and the width is not theoretical: a component sheet may reference a
 *   property declared inside a class in a sheet its own component never imports, as `--gutter-w` is declared
 *   inside `.gutter` in `layout/Gutter.css`. Such a reference resolves to nothing twice over -- the sheet is
 *   not loaded, and the property is scoped to a class this element is not inside -- and the wide model passes it
 *
 * So the closure is walked. For each stylesheet, the modules that import it are found, each module's transitive
 * imports are followed, and the stylesheets reached that way are what that sheet may read from. A sheet imported by
 * two components is judged against the INTERSECTION of their closures, because a reference has to resolve in every
 * context the sheet is loaded in, and that is the fail-closed direction this repository takes everywhere else.
 *
 * CSS `@import` is an edge too: `theme.css` pulls the token layer and `base.css` in that way, and a sheet reached
 * only through an `@import` chain is as loaded as one reached through a module. */

import { readFile } from "node:fs/promises";

import { blankJsComments } from "./comments.ts";
import { scanCss } from "./css-scan.ts";
import { importSitesIn, resolveSpecifier, type Exists } from "./module-graph.ts";

const STYLESHEET = /\.css$/;

export interface ClosureInput {
  /** Absolute paths of every module and stylesheet the application ships. */
  readonly files: readonly string[];
  readonly exists: Exists;
}

/** What each file imports, resolved to absolute paths. */
async function edgesOf(input: ClosureInput): Promise<Map<string, string[]>> {
  const edges = new Map<string, string[]>();
  for (const file of input.files) {
    const source = await readFile(file, "utf8");
    const specifiers = STYLESHEET.test(file)
      ? scanCss(source).imports.map((each) => each.specifier)
      : importSitesIn(blankJsComments(source))
          .filter((site) => !site.computed)
          .map((site) => site.specifier);
    const resolved: string[] = [];
    for (const specifier of specifiers) {
      if (!specifier.startsWith(".")) continue;
      const target = await resolveSpecifier(file, specifier, input.exists);
      if (target !== null) resolved.push(target);
    }
    edges.set(file, resolved);
  }
  return edges;
}

/** Every file reachable from a root, including the root itself. */
function reachableFrom(root: string, edges: ReadonlyMap<string, string[]>): Set<string> {
  const seen = new Set<string>([root]);
  const pending = [root];
  while (pending.length > 0) {
    const next = pending.pop();
    if (next === undefined) continue;
    for (const target of edges.get(next) ?? []) {
      if (seen.has(target)) continue;
      seen.add(target);
      pending.push(target);
    }
  }
  return seen;
}

export interface StylesheetClosure {
  /** The stylesheets loaded alongside this one, in every context that loads it. */
  readonly loadedWith: ReadonlySet<string>;
  /** The modules and sheets that import it. Empty means nothing loads this sheet at all. */
  readonly importers: readonly string[];
}

/**
 * For each stylesheet, the sheets it is loaded with.
 *
 * A sheet nobody imports gets an empty closure and an empty importer list, which is a fact worth having rather
 * than a special case: a stylesheet no module loads reaches no browser, and its references resolve against nothing.
 */
export async function stylesheetClosures(
  input: ClosureInput,
): Promise<Map<string, StylesheetClosure>> {
  const edges = await edgesOf(input);
  const sheets = input.files.filter((file) => STYLESHEET.test(file));
  const closures = new Map<string, StylesheetClosure>();

  for (const sheet of sheets) {
    const importers = [...edges]
      .filter(([, targets]) => targets.includes(sheet))
      .map(([from]) => from);
    const perImporter = importers.map(
      (importer) =>
        new Set([...reachableFrom(importer, edges)].filter((file) => STYLESHEET.test(file))),
    );
    /* The intersection, because a reference has to resolve in every context the sheet is loaded in. A sheet
     * nobody imports is judged against itself alone, which is what it would have in a browser: nothing. */
    const loadedWith = new Set(perImporter[0] ?? [sheet]);
    for (const reached of perImporter.slice(1)) {
      for (const file of loadedWith) {
        if (!reached.has(file)) loadedWith.delete(file);
      }
    }
    closures.set(sheet, { loadedWith, importers });
  }
  return closures;
}
