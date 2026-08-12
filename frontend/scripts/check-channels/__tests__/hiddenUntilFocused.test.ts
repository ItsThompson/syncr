/* THE CHANNEL IS DECLARED IN THREE FILES AND NO ONE OF THEM WORKS ALONE.
 *
 * `channels.ts` names the properties the treatment spends, `tokens/layout.css` carries the values it spends
 * them at, and `docs/DESIGN-LANGUAGE.md` says what the vocabulary governs and which control takes this
 * channel and no other. Neither committed gate crosses them. `lint:channels` counts how many files assign a
 * (state, channel) pair and reports nothing about which files those are, so it stays green with the pair in
 * one wrong file and green with it in none. `lint:tokens` refuses a `var()` that resolves to nothing, not
 * one that resolves from the wrong file, and it says nothing at all about a declared name no sheet reads.
 * So a treatment moved out of the token layer into a component, or a channel the design language stops
 * naming, is invisible to every check in the tree. These cases pin the three to each other. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { repoRoot, tokenDir } from "../../lib/paths.ts";
import { channelFor, unchannelledReason } from "../channels.ts";

const CHANNEL = "hidden until focused";
const FOCUS = ":focus-visible";

/** The properties the treatment spends. Written here rather than read from the model, so the model can fail. */
const TREATMENT = ["position", "width", "height", "overflow", "clip-path", "margin"] as const;

/** The figures the token layer carries, so no component restates one. */
const TOKENS: ReadonlyMap<string, string> = new Map([
  ["--state-hidden-size", "1px"],
  ["--state-hidden-clip", "inset(50%)"],
]);

const here = path.dirname(fileURLToPath(import.meta.url));
const fixtureFile = path.join(here, "..", "__fixtures__", "focus-reveal.css");
const layoutFile = path.join(tokenDir, "layout.css");

/** Every custom property a stylesheet declares, in the order it declares them. */
async function declarationsIn(file: string): Promise<{ name: string; value: string }[]> {
  const found: { name: string; value: string }[] = [];
  parse(await readFile(file, "utf8")).walkDecls((declaration) => {
    if (declaration.prop.startsWith("--")) {
      found.push({ name: declaration.prop, value: declaration.value.trim() });
    }
  });
  return found;
}

/** Every file of the token layer except `layout.css`, which is where the state vocabulary belongs. */
async function otherTokenFiles(): Promise<string[]> {
  const entries = await readdir(tokenDir, { withFileTypes: true });
  return entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".css") && entry.name !== "layout.css")
    .map((entry) => path.join(tokenDir, entry.name));
}

/** One section of the design language, from its own heading to the next one at that level. */
async function sectionOf(heading: string): Promise<string> {
  const doc = await readFile(path.join(repoRoot, "docs", "DESIGN-LANGUAGE.md"), "utf8");
  const section = doc.split(/^## /m).find((part) => part.startsWith(`${heading}\n`));
  if (section === undefined) throw new Error(`the design language has no ${heading} section`);
  return section;
}

/* The doc writes the channel as a compound adjective and the model writes it as a name, so the lines are
 * matched with hyphens flattened: what the case is about is both surfaces saying the same words. */
async function sentenceNamingTheChannel(): Promise<string[]> {
  const section = await sectionOf("Interaction states");
  return section
    .split("\n")
    .map((line) => line.replaceAll("-", " "))
    .filter((line) => line.includes(CHANNEL));
}

describe("the model names the treatment", () => {
  it("carries every property of it under the focus state", () => {
    const carried = TREATMENT.map((property) => channelFor(property, FOCUS));

    expect(carried).toEqual(TREATMENT.map(() => CHANNEL));
  });

  /* A visibility channel invites a second state to spend it, and `states` is what forecloses that. Both
   * edges are read, because a set-membership reading is blind to a removal as a count is to an addition. */
  it("carries none of it under a state that is not focus", () => {
    for (const state of ["data-current", "data-highlighted", ":hover", "data-selected"]) {
      for (const property of TREATMENT) {
        expect(channelFor(property, state)).toBeNull();
      }
    }
  });

  it("leaves position to the exemption everywhere except the focus state", () => {
    expect(unchannelledReason("position", "data-highlighted")).toContain("stacking context");
    expect(unchannelledReason("position", ":hover")).toContain("stacking context");
  });
});

describe("the token layer carries the treatment's figures", () => {
  it("declares each of them in layout.css", async () => {
    const declared = new Map(
      (await declarationsIn(layoutFile)).map(({ name, value }) => [name, value]),
    );

    for (const [name, value] of TOKENS) expect(declared.get(name)).toBe(value);
  });

  it("declares them nowhere else in the layer, so there is one home to read them from", async () => {
    const files = await otherTokenFiles();
    const copies = await Promise.all(
      files.map(async (file) =>
        (await declarationsIn(file))
          .filter(({ name }) => TOKENS.has(name))
          .map(({ name }) => `${path.basename(file)} declares ${name}`),
      ),
    );

    expect(copies.flat()).toEqual([]);
    expect(files.map((file) => path.basename(file)).toSorted()).toEqual([
      "color.css",
      "index.css",
      "primitives.css",
      "type.css",
    ]);
  });

  /* The `--state-*` block is a position in the file rather than a syntax, so what is checkable is that the
   * group is unbroken: a token dropped at the end of the file, or up among the geometry, splits it. */
  it("keeps them inside the unbroken --state- group rather than loose in the file", async () => {
    const names = (await declarationsIn(layoutFile)).map(({ name }) => name);
    const positions = names.reduce<number[]>((found, name, index) => {
      if (name.startsWith("--state-")) found.push(index);
      return found;
    }, []);
    const span = positions[positions.length - 1] - positions[0] + 1;

    expect(span).toBe(positions.length);
    for (const name of TOKENS.keys()) {
      expect(names.indexOf(name)).toBeGreaterThanOrEqual(positions[0]);
      expect(names.indexOf(name)).toBeLessThanOrEqual(positions[positions.length - 1]);
    }
  });

  /* The reading's control on both edges. A layout.css that parsed to nothing would pass every case above,
   * and a group that had swallowed the whole file would pass the contiguity one. */
  it("is read from a file that declares the rest of the vocabulary and more besides", async () => {
    const names = (await declarationsIn(layoutFile)).map(({ name }) => name);
    const state = names.filter((name) => name.startsWith("--state-"));

    expect(state).toContain("--state-margin");
    expect(state).toContain("--state-focus-ring");
    expect(state.length).toBeGreaterThan(8);
    expect(names.length).toBeGreaterThan(state.length);
  });

  /* The fixture that arms the channel spends the treatment through these names, so a rename that missed it
   * would leave the fixture green against tokens nothing declares. */
  it("declares every state token the fixture spends the treatment through", async () => {
    const fixture = await readFile(fixtureFile, "utf8");
    const read = [...fixture.matchAll(/var\((--state-[a-z-]+)\)/g)].map((match) => match[1]);
    const declared = new Set((await declarationsIn(layoutFile)).map(({ name }) => name));

    expect(read).toContain("--state-hidden-size");
    expect(read).toContain("--state-hidden-clip");
    expect(read.filter((name) => !declared.has(name))).toEqual([]);
  });
});

describe("the design language says what the vocabulary governs", () => {
  it("names this channel in one sentence of the interaction states section", async () => {
    expect(await sentenceNamingTheChannel()).toHaveLength(1);
  });

  it("says the vocabulary governs marks on an object compared across states, and that this control takes one channel", async () => {
    const [sentence] = await sentenceNamingTheChannel();

    expect(sentence).toContain("compares across states");
    expect(sentence).toContain("only while it holds focus");
    expect(sentence).toContain("and no other");
  });

  it("is read from a section that carries the rest of the vocabulary", async () => {
    const section = await sectionOf("Interaction states");

    expect(section).toContain("Each state owns exactly one channel");
    expect(section).toContain("glyph slot");
  });
});
