/* THE SIX HATCHES, DERIVED FROM THE TOKEN LAYER RATHER THAN TRUSTED.
 *
 * `hatch.ts` holds angles, pitches and line widths as numbers because an SVG `<pattern>` takes its tile size and
 * its rotation as ATTRIBUTES, and an attribute cannot hold a `var()`. That makes those numbers a second statement
 * of what `tokens/color.css` already declares as gradients, so this file resolves the question the only way it
 * can be resolved across that boundary: the token declarations are parsed, the geometry is derived from them, and
 * a disagreement fails here.
 *
 * THE LEDGER OF WHICH AREA HOLDS WHICH HATCH IS READ FROM THE RENDERED SHEET for the same reason. The design
 * language states that the sheets and the kit must not disagree about it, and `specimen.html` carries the copy
 * every other sheet was ported from.
 *
 * THE ROTATION IS CHECKED BY ARITHMETIC, NOT BY THE FORMULA THAT PRODUCED IT. A CSS gradient angle and an SVG
 * pattern rotation are two coordinate conventions, so each stripe direction is derived from first principles and
 * the two are asserted parallel. Reproducing `patternRotation`'s own expression would assert nothing. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { scanCss } from "../../../../../scripts/lib/css-scan.ts";
import { designSheetDir } from "../../../../../scripts/lib/paths.ts";
import { srcDir } from "../../../../testing/compileTheme";
import { AREA_PIGMENTS } from "../../marks/pigment";
import {
  AREA_HATCHES,
  HATCH_GEOMETRY,
  HATCH_NAMES,
  distinctPigments,
  hatchFor,
  patternRotation,
  type HatchName,
} from "../hatch";
import { UNALLOCATED } from "../series";

const HALF_TURN = 180;

async function tokenValues(): Promise<Map<string, string>> {
  const scan = scanCss(await readFile(path.join(srcDir, "tokens", "color.css"), "utf8"));
  return new Map(scan.declarations.map((declaration) => [declaration.name, declaration.value]));
}

/** Every `Ndeg` a gradient declares, which is the angle its stripes are laid across. */
function anglesIn(value: string): number[] {
  return [...value.matchAll(/(-?\d+(?:\.\d+)?)deg/g)].map((match) => Number(match[1]));
}

/**
 * The line width and the pitch a repeating gradient declares.
 *
 * The stops read `var(--hatch-ink) 0 Wpx, transparent Wpx Ppx`: the ink runs to the line's width and the
 * transparent band runs to the pitch.
 */
function stripeStops(value: string): { lineWidth: number; pitch: number } {
  const stops = /var\(--hatch-ink\)\s+0\s+([\d.]+)px,\s*transparent\s+[\d.]+px\s+([\d.]+)px/.exec(
    value,
  );
  if (stops === null) throw new Error(`no repeating stops in ${value}`);
  return { lineWidth: Number(stops[1]), pitch: Number(stops[2]) };
}

/** The direction a CSS gradient's stripes run, in screen coordinates where y points down. */
function stripeDirectionFromGradient(angle: number): { x: number; y: number } {
  const radians = (angle * Math.PI) / HALF_TURN;
  return { x: Math.cos(radians), y: Math.sin(radians) };
}

/** The direction a vertical line in an SVG tile runs after `patternTransform: rotate(rotation)`. */
function stripeDirectionFromTile(rotation: number): { x: number; y: number } {
  const radians = (rotation * Math.PI) / HALF_TURN;
  return { x: -Math.sin(radians), y: Math.cos(radians) };
}

function areParallel(one: { x: number; y: number }, two: { x: number; y: number }): boolean {
  return Math.abs(one.x * two.y - one.y * two.x) < 1e-9;
}

describe("the geometry the pie's patterns are drawn with", () => {
  it.each(["fwd", "back", "vert", "horz"] as const)(
    "matches the angle, line width and pitch --hatch-%s declares",
    async (name) => {
      const declared = (await tokenValues()).get(`--hatch-${name}`);
      const geometry = HATCH_GEOMETRY[name];

      expect(declared).toBeDefined();
      expect(geometry).toEqual({
        kind: "stripes",
        angles: anglesIn(declared ?? ""),
        ...stripeStops(declared ?? ""),
      });
    },
  );

  it("matches both angles the cross declares, and its wider pitch", async () => {
    const declared = (await tokenValues()).get("--hatch-cross") ?? "";

    expect(anglesIn(declared)).toHaveLength(2);
    expect(HATCH_GEOMETRY.cross).toEqual({
      kind: "stripes",
      angles: anglesIn(declared),
      ...stripeStops(declared),
    });
  });

  /* One rotation carries both of the cross's families, which is only true because they are perpendicular: the
   * tile holds a vertical line and a horizontal one, and rotating the tile rotates both. */
  it("draws the cross as two perpendicular families, which is what lets one tile hold both", () => {
    const cross = HATCH_GEOMETRY.cross;
    if (cross.kind !== "stripes") throw new Error("the cross is a stripe pattern");

    expect(Math.abs(cross.angles[0] - cross.angles[1]) % HALF_TURN).toBe(90);
  });

  it("matches the radius and the tile the dot declares", async () => {
    const tokens = await tokenValues();
    const radius = /var\(--hatch-ink\)\s+([\d.]+)px/.exec(tokens.get("--hatch-dot") ?? "");
    const tile = /^([\d.]+)px\s+([\d.]+)px$/.exec(tokens.get("--hatch-dot-size") ?? "");

    expect(HATCH_GEOMETRY.dot).toEqual({
      kind: "dots",
      radius: Number(radius?.[1]),
      pitch: Number(tile?.[1]),
    });
    // A square tile, because a dot grid with two pitches is two patterns pretending to be one.
    expect(tile?.[1]).toBe(tile?.[2]);
  });

  it("holds a geometry for every pattern the token layer declares, and no other", async () => {
    /* A pattern is a hatch token whose value is a gradient. `--hatch-ink` is caller-provided and `--hatch-mix` is
     * the lightening step, so naming them by hand here would be a list to keep in step with the token file. */
    const declared = [...(await tokenValues())]
      .filter(([name, value]) => name.startsWith("--hatch-") && value.includes("gradient("))
      .map(([name]) => name.replace("--hatch-", ""))
      .toSorted();

    expect(Object.keys(HATCH_GEOMETRY).toSorted()).toEqual(declared);
    // Six is the honest ceiling: past that they stop separating at wedge scale.
    expect(HATCH_NAMES).toHaveLength(6);
  });
});

describe("the rotation that turns a tile of lines into a gradient's stripes", () => {
  it.each(HATCH_NAMES.filter((name) => name !== "dot"))(
    "puts %s's tile on the same line the token's gradient draws",
    (name) => {
      const geometry = HATCH_GEOMETRY[name];
      if (geometry.kind !== "stripes") throw new Error("expected stripes");
      const rotation = patternRotation(geometry.angles[0]);

      expect(
        areParallel(
          stripeDirectionFromGradient(geometry.angles[0]),
          stripeDirectionFromTile(rotation),
        ),
      ).toBe(true);
    },
  );

  it("answers modulo a half turn, because a line has no direction", () => {
    expect(patternRotation(0)).toBe(90);
    expect(patternRotation(90)).toBe(0);
    expect(patternRotation(135)).toBe(45);
  });
});

describe("which Area holds which hatch", () => {
  it("agrees with the ledger the rendered specimen carries", async () => {
    const sheet = await readFile(path.join(designSheetDir, "specimen.html"), "utf8");
    const rendered = new Map(
      [...sheet.matchAll(/\{n:'(\d\d)',[^}]*hatch:'([a-z]+)'/g)].map((match) => [
        match[1],
        match[2],
      ]),
    );

    expect(rendered.size).toBe(AREA_PIGMENTS.length);
    expect(Object.fromEntries(rendered)).toEqual(AREA_HATCHES);
  });

  it("gives every step of the sealed ramp one, and only a step of it", () => {
    expect(Object.keys(AREA_HATCHES).toSorted()).toEqual([...AREA_PIGMENTS].toSorted());
    for (const hatch of Object.values(AREA_HATCHES)) {
      expect(HATCH_NAMES).toContain(hatch);
    }
  });

  /* WHAT PROTECTS TWO ADJACENT PIGMENTS IS THAT THEY CARRY DIFFERENT TEXTURES. The ramp's tightest hue gaps are
   * around 20 degrees, which is not far enough for two dark colours to separate on a wedge. */
  it("never repeats a pattern between neighbouring steps", () => {
    const steps = [...AREA_PIGMENTS];
    for (let index = 0; index < steps.length; index += 1) {
      const next = steps[(index + 1) % steps.length];
      expect(AREA_HATCHES[steps[index]], `${steps[index]} and ${next} share a hatch`).not.toBe(
        AREA_HATCHES[next],
      );
    }
  });

  it("gives the vacancy none, because there is no Area for a texture to be redundant about", () => {
    expect(hatchFor(UNALLOCATED)).toBeNull();
  });

  /* PAST TWELVE AREAS THE PAIR REPEATS, and this is the measurement of that rather than a claim about it. The
   * wire carries a step of the ramp, not the deal, so a thirteenth Area arrives holding the first step and a
   * chart cannot tell the two apart. Identity then rests on the NAME alone, which is why every wedge is
   * labelled: the design language and `syncr_domain.pigments` both say "the hatch and the Area name", and the
   * hatch half is not available in this case. */
  it("repeats with the pigment past twelve, so the name is what separates a thirteenth Area", () => {
    const thirteenth = AREA_PIGMENTS[0];

    expect(hatchFor(thirteenth)).toBe(hatchFor(AREA_PIGMENTS[0]));
    expect(new Set(Object.values(AREA_HATCHES)).size).toBeLessThan(AREA_PIGMENTS.length);
  });
});

describe("the pigments a chart declares a pattern for", () => {
  it("names each once, in the order they first appear", () => {
    expect(distinctPigments(["05", "01", "05", UNALLOCATED, "01"])).toEqual([
      "05",
      "01",
      UNALLOCATED,
    ]);
  });

  it("is empty for an empty composition", () => {
    expect(distinctPigments([])).toEqual([]);
  });
});

describe("the hatch names", () => {
  it("are the six the sheet names, so a seventh cannot arrive unnamed", () => {
    const named: readonly HatchName[] = ["fwd", "back", "vert", "horz", "cross", "dot"];

    expect([...HATCH_NAMES].toSorted()).toEqual([...named].toSorted());
  });
});
