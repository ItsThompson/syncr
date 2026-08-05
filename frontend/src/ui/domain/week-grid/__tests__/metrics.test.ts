/* EVERY NUMBER THE ARITHMETIC USES, HELD AGAINST THE TOKEN THAT DRAWS IT.
 *
 * TypeScript cannot read a custom property, so the geometry's constants are a second spelling of the token layer's
 * declarations. This is what makes the duplicate incapable of drifting: each constant is read back out of the file
 * that declares it and compared. Renaming a token, retuning one, or moving one between layers fails here rather
 * than silently leaving the grid computing against a value nothing draws with.
 *
 * The reader takes the property AND the file, because the answer to "where is this declared" is part of what is
 * being asserted: `--snap` staying in layer 1 while `--grid-minor` moved to layer 2 is a fact this file pins. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { parse } from "postcss";

import { srcDir } from "../../../../testing/compileTheme";
import {
  AREA_RULE_PX,
  AXIS_W_PX,
  BLOCK_H_COMPACT_PX,
  BLOCK_H_LABEL_PX,
  BLOCK_H_SLIVER_PX,
  BLOCK_PAD_T_PX,
  BOTTOM_RULE_PX,
  DAY_HEADER_H_PX,
  GRID_H_PX,
  GRID_MAJOR_MINUTES,
  GRID_MINOR_MINUTES,
  LINE_HEIGHT_PX,
  OVERLAP_MAX_SPLIT,
  VISIBLE_HOURS_DEFAULT,
  ZOOM_MAX_HOURS,
  ZOOM_MIN_HOURS,
} from "../metrics";
import { SNAP_MINUTES } from "../../../primitives";

const GRID_TOKENS = path.join(srcDir, "ui", "domain", "week-grid", "tokens.css");
const LAYOUT_TOKENS = path.join(srcDir, "tokens", "layout.css");
const TYPE_TOKENS = path.join(srcDir, "tokens", "type.css");

/** The declared value of a custom property in a file, or null when the file does not declare it. */
async function declared(file: string, property: string): Promise<string | null> {
  let found: string | null = null;
  parse(await readFile(file, "utf8")).walkDecls((declaration) => {
    if (declaration.prop === property) found = declaration.value.trim();
  });
  return found;
}

/** The number a length token carries, so `19px` and `19` compare as the same figure. */
async function figure(file: string, property: string): Promise<number | null> {
  const value = await declared(file, property);
  return value === null ? null : Number.parseFloat(value);
}

describe("the grid's own tokens, promoted to layer 2", () => {
  it.each([
    ["--block-h-label", BLOCK_H_LABEL_PX],
    ["--block-h-compact", BLOCK_H_COMPACT_PX],
    ["--block-h-sliver", BLOCK_H_SLIVER_PX],
    ["--block-pad-t", BLOCK_PAD_T_PX],
    ["--grid-major", GRID_MAJOR_MINUTES],
    ["--grid-minor", GRID_MINOR_MINUTES],
    ["--overlap-max-split", OVERLAP_MAX_SPLIT],
    ["--visible-hours", VISIBLE_HOURS_DEFAULT],
    ["--grid-h", GRID_H_PX],
    ["--day-header-h", DAY_HEADER_H_PX],
    ["--axis-w", AXIS_W_PX],
  ])("%s equals the constant that mirrors it", async (property, constant) => {
    expect(await figure(GRID_TOKENS, property)).toBe(constant);
  });
});

describe("the layer 1 tokens the grid reads without owning", () => {
  it.each([
    ["--rule-emphasis", AREA_RULE_PX],
    ["--hairline", BOTTOM_RULE_PX],
    ["--zoom-min", ZOOM_MIN_HOURS],
    ["--zoom-max", ZOOM_MAX_HOURS],
  ])("%s equals the constant that mirrors it", async (property, constant) => {
    expect(await figure(LAYOUT_TOKENS, property)).toBe(constant);
  });

  it("--lh-block-px is one line of block title, and the line count divides by it", async () => {
    expect(await figure(TYPE_TOKENS, "--lh-block-px")).toBe(LINE_HEIGHT_PX);
  });
});

/* THE PROMOTION IS A RENAME OF LOCATION, so a token may not be declared in both places at once: the later
 * declaration would win in the cascade and the earlier one would be a value nothing draws with and nothing
 * reports. Asserted in both directions, because a copy left behind and a copy moved back are the same defect. */
describe("the promotion left no second copy", () => {
  it.each([
    "--block-h-label",
    "--block-h-compact",
    "--block-h-sliver",
    "--block-pad-x",
    "--block-pad-t",
    "--block-pad-b",
    "--overlap-max-split",
    "--overlap-indent",
    "--grid-h",
    "--grid-major",
    "--grid-minor",
    "--grid-line-hour",
    "--grid-line-quarter",
    "--grid-line-quarter-drag",
    "--grid-inset",
    "--px-per-min",
    "--visible-hours",
    "--axis-w",
    "--day-header-h",
  ])("%s is declared beside the grid and not in layer 1", async (property) => {
    expect(await declared(GRID_TOKENS, property)).not.toBeNull();
    expect(await declared(LAYOUT_TOKENS, property)).toBeNull();
  });

  it.each(["--snap", "--strip-h", "--verdict-h", "--clause-label-w", "--col-min", "--bp-compact"])(
    "%s stayed in layer 1, because something other than the grid reads it",
    async (property) => {
      expect(await declared(LAYOUT_TOKENS, property)).not.toBeNull();
      expect(await declared(GRID_TOKENS, property)).toBeNull();
    },
  );
});

/* The quarter line is drawn at rest BECAUSE the snap is fifteen minutes, so the two figures are one decision. They
 * are declared in two layers now -- the snap where a primitive can read it, the line spacing beside the grid -- and
 * this is the assertion that keeps them one decision rather than two that happen to agree. */
describe("the quarter line and the snap", () => {
  it("are the same figure, declared in two layers", async () => {
    expect(GRID_MINOR_MINUTES).toBe(SNAP_MINUTES);
    expect(await figure(GRID_TOKENS, "--grid-minor")).toBe(await figure(LAYOUT_TOKENS, "--snap"));
  });
});
