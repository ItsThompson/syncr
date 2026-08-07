/* WHAT A DIALOG'S SCRIM MAY COVER, AND WHAT IT MAY NOT.
 *
 * FOUND IN A BROWSER AND NOT IN A TEST, which is why it is asserted from the stylesheets rather than from a
 * rendering: jsdom lays nothing out, so `getComputedStyle` on a portal'd list says nothing about what a pointer
 * would hit. The capture form's Area select rendered its list where a reader could see it and could not click it,
 * because Radix portals a select's list to the document root and the dialog's scrim covers the viewport at a
 * higher layer.
 *
 * THE SET IS DERIVED RATHER THAN NAMED, and that is why this file was rewritten after review. Naming
 * `.select__content` and `.date-picker__panel` bounds the pair that broke and not the claim the guard makes: FOUR
 * components in this kit portal to the document root, `@radix-ui/react-popover` is a declared dependency with no
 * primitive of its own yet, and the next one added would reproduce the defect with this check still green. So the
 * portalling components are read from the kit's own source, their surface classes are resolved against the kit's
 * own sheets, and a portal that lands on no layer at all is the finding.
 *
 * The numbers still live in four sheets rather than in the token layer as one ladder, which is ticket 1461. Until
 * that lands, this is what keeps the ordering honest. */

import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { classListsIn } from "../../../testing/kitSources";
import { domainDir, layoutDir, primitivesDir } from "../../../testing/kitStylesheets";

const LAYERS = [primitivesDir, layoutDir, domainDir];

/** Every file under the kit with the extension given, tests excluded. */
async function kitFiles(extension: string): Promise<string[]> {
  const perLayer = await Promise.all(
    LAYERS.map((layer) => readdir(layer, { withFileTypes: true, recursive: true })),
  );
  return perLayer
    .flat()
    .filter((entry) => entry.isFile() && entry.name.endsWith(extension))
    .filter((entry) => !entry.name.includes(".test."))
    .map((entry) => path.join(entry.parentPath, entry.name))
    .toSorted();
}

/** Each file's path and its source, read in one pass. */
async function sourcesOf(extension: string): Promise<{ file: string; source: string }[]> {
  const files = await kitFiles(extension);
  return Promise.all(files.map(async (file) => ({ file, source: await readFile(file, "utf8") })));
}

/** Every `z-index` the kit declares, by the class the rule selects on. */
async function layersByClass(): Promise<Map<string, number>> {
  const layers = new Map<string, number>();
  for (const { source } of await sourcesOf(".css")) {
    for (const rule of source.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const declared = /z-index:\s*(\d+)/.exec(rule[2]);
      if (declared === null) continue;
      for (const named of rule[1].matchAll(/\.([a-z][a-z0-9_-]*)/g)) {
        layers.set(named[1], Math.max(layers.get(named[1]) ?? 0, Number(declared[1])));
      }
    }
  }
  return layers;
}

interface PortalledSurface {
  /** The file a finding names, so a reader knows which component to open. */
  readonly name: string;
  /** The highest layer any class it draws with resolves to, or null when none of them declares one. */
  readonly layer: number | null;
}

/** Every component in the kit that portals to the document root, with the layer its surfaces land on. */
async function portalled(): Promise<PortalledSurface[]> {
  const layers = await layersByClass();
  return (await sourcesOf(".tsx"))
    .filter(({ source }) => source.includes(".Portal"))
    .map(({ file, source }) => {
      let highest: number | null = null;
      for (const classList of classListsIn(source)) {
        for (const named of classList.split(/\s+/)) {
          const declared = layers.get(named);
          if (declared !== undefined) highest = Math.max(highest ?? 0, declared);
        }
      }
      return { name: path.basename(file), layer: highest };
    })
    .toSorted((left, right) => left.name.localeCompare(right.name));
}

describe("the kit's portalled surfaces", () => {
  it("are found by reading the kit rather than by naming a pair", async () => {
    const surfaces = await portalled();

    /* Named as well as counted, so a portal that stops portalling is as visible as one that arrives. */
    expect(surfaces.map((surface) => surface.name)).toEqual([
      "CommandPalette.tsx",
      "DatePicker.tsx",
      "Dialog.tsx",
      "Select.tsx",
    ]);
  });

  /* A portal leaves its parent's stacking context entirely, so a surface that declares no layer is at the mercy
     of document order against every scrim in the product. That is the shape the scrim defect had. */
  it("all land on a layer, so none is left to document order", async () => {
    expect((await portalled()).filter((surface) => surface.layer === null)).toEqual([]);
  });

  /* The claim the fix makes: a control a dialog can contain floats above the scrim. Every portal that is not a
     scrim itself has to clear it, because a reader can open a select inside a dialog and cannot open a dialog
     inside a select. */
  it("float above a dialog's scrim, because a list under it can be seen and not clicked", async () => {
    const scrim = (await layersByClass()).get("overlay__scrim");
    const popovers = (await portalled()).filter((surface) => surface.layer !== scrim);

    expect(scrim).toBe(50);
    expect(popovers.map((surface) => surface.name)).toEqual(["DatePicker.tsx", "Select.tsx"]);
    for (const surface of popovers) {
      expect(surface.layer ?? 0).toBeGreaterThan(scrim ?? 0);
    }
  });

  /* The scrim still covers the page it dims. A ladder that lifted every popover above everything would put a
     select's list over a dialog it does not belong to, so the ordering is asserted from both ends. */
  it("leave the scrim above the surfaces the page itself stacks", async () => {
    const layers = await layersByClass();

    expect(layers.get("overlay__scrim") ?? 0).toBeGreaterThan(layers.get("week-insertion") ?? 0);
  });
});
