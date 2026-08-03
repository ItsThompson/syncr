/* THE AREA RAMP'S HUE LEDGER, DERIVED FROM THE PIGMENTS RATHER THAN WRITTEN BESIDE THEM.
 *
 * `tokens/primitives.css` states a hue for each of the twelve Area pigments, and the spacing between them is the
 * reason the ramp is legible at all: twelve dark colours at five-to-one on paper separate by hue and by nothing
 * else. Every figure in that comment used to be asserted, and it drifted: an earlier version misreported the
 * tightest pair as 02/03 at 23 degrees, and `docs/design/specimen.html` still holds a hardcoded ledger that
 * disagrees with the retuned pigments on all twelve steps and reproduces exactly that stale 23.
 *
 * So the hue is COMPUTED FROM THE HEX. There is one authority, the pigment itself, and both ledgers are checked
 * against it: a comment that disagrees is a finding, and a second copy in a reference sheet is a finding. That is
 * the same rule check 6 applies to the sheets, which exists to stop a sheet becoming the second copy of the values
 * it was built to avoid.
 *
 * TWO FLOORS ARE ENFORCED, and each is a rule the design language states rather than a number chosen here:
 *
 *   the tightest ADJACENT gap around the circle, because below it two dark colours stop separating at wedge
 *   scale, which is what the 07 retune from 183 to 176 degrees was for
 *
 *   the spacing of the FIRST FOUR DEALT, because pigments are assigned in an order chosen so that a user with
 *   four Areas gets four that are far apart, and that order is worth nothing if the spacing is not checked */

import { readFile } from "node:fs/promises";
import path from "node:path";

import { scanCss, createPositionResolver } from "../lib/css-scan.ts";
import type { Finding } from "../lib/findings.ts";
import { tokenDir } from "../lib/paths.ts";

/**
 * The tightest adjacent gap the ramp may hold, in degrees.
 *
 * 19 rather than 20 because the shipped ramp's tightest pair is 02/03 at 19.4, and the design language records
 * that as about as tight as two dark colours can be and still separate. At 13.0 degrees, which is where 07 sat
 * before it was retuned, the pair was genuinely indistinguishable.
 */
export const SEPARATION_FLOOR = 19;

/**
 * How far apart the first four dealt pigments have to be, in degrees.
 *
 * `color.css` states the deal order and the promise it exists to keep: a user with four Areas gets four pigments
 * far apart. The shipped ramp's closest of those six pairs is 01/10 at 75.3 degrees.
 */
export const ASSIGNMENT_FLOOR = 75;

/** The order pigments are dealt in, which is not numeric order. Stated in `color.css` and read here. */
const DEAL_ORDER = ["01", "05", "08", "10", "03", "07", "12", "06", "02", "04", "09", "11"];

const AREA_PIGMENT = /^--pigment-area-(\d{2})$/;
/** The hue each pigment's own trailing comment claims, as `#AB4757; /* 350  madder`. */
const COMMENTED_HUE = /--pigment-area-(\d{2}):\s*(#[0-9a-fA-F]{6});\s*\/\*\s*(\d{1,3})\b/g;
/** The hardcoded ledger in a reference sheet: `{n:'01', hue:355, ...}`, in either quote style. */
const SHEET_HUE = /\{\s*n:\s*["'](\d{2})["']\s*,\s*hue:\s*(\d{1,3})/g;

export interface AreaHue {
  readonly id: string;
  readonly hex: string;
  /** Degrees, one decimal place, derived from the hex. */
  readonly hue: number;
}

export interface HueGap {
  readonly pair: string;
  readonly gap: number;
}

/** The hue of a six-digit hex, in degrees. */
export function hueOf(hex: string): number {
  const value = Number.parseInt(hex.slice(1), 16);
  const red = ((value >> 16) & 0xff) / 255;
  const green = ((value >> 8) & 0xff) / 255;
  const blue = (value & 0xff) / 255;
  const highest = Math.max(red, green, blue);
  const span = highest - Math.min(red, green, blue);
  if (span === 0) return 0;
  const sixth =
    highest === red
      ? ((green - blue) / span) % 6
      : highest === green
        ? (blue - red) / span + 2
        : (red - green) / span + 4;
  return Number((((sixth * 60) % 360) + 360) % 360);
}

/** The shorter way round the circle between two hues. */
function separation(one: number, two: number): number {
  const direct = Math.abs(one - two) % 360;
  return Math.min(direct, 360 - direct);
}

const rounded = (hue: number): number => Number(hue.toFixed(1));

/** Every Area pigment in the layer, with its hue derived from its own hex. */
export function areaHues(source: string): AreaHue[] {
  const found: AreaHue[] = [];
  for (const declaration of scanCss(source).declarations) {
    const matched = AREA_PIGMENT.exec(declaration.name);
    if (matched === null) continue;
    const hex = /^#[0-9a-fA-F]{6}$/.exec(declaration.value.trim());
    if (hex === null) continue;
    found.push({ id: matched[1], hex: hex[0], hue: rounded(hueOf(hex[0])) });
  }
  return found.toSorted((one, two) => one.id.localeCompare(two.id));
}

/** The gap between each pigment and its neighbour around the hue circle, in hue order. */
export function adjacentGaps(hues: readonly AreaHue[]): HueGap[] {
  const byHue = [...hues].toSorted((one, two) => one.hue - two.hue);
  return byHue.map((pigment, index) => {
    const next = byHue[(index + 1) % byHue.length];
    return {
      pair: `${pigment.id}/${next.id}`,
      gap: rounded((next.hue - pigment.hue + 360) % 360),
    };
  });
}

/** Every pair among the first four dealt, which is the promise the deal order exists to keep. */
export function firstFourPairs(hues: readonly AreaHue[]): HueGap[] {
  const dealt = DEAL_ORDER.slice(0, 4).flatMap((id) => hues.filter((hue) => hue.id === id));
  const pairs: HueGap[] = [];
  for (let one = 0; one < dealt.length; one += 1) {
    for (let two = one + 1; two < dealt.length; two += 1) {
      pairs.push({
        pair: `${dealt[one].id}/${dealt[two].id}`,
        gap: rounded(separation(dealt[one].hue, dealt[two].hue)),
      });
    }
  }
  return pairs;
}

export interface HueCheckInput {
  /** Absolute path of the layer 0 file that declares the Area pigments. */
  readonly pigmentFile: string;
  /** Absolute paths of the reference sheets, which may hold no second copy of the ledger. */
  readonly sheetFiles: readonly string[];
}

export interface HueCheckOutcome {
  readonly findings: readonly Finding[];
  readonly notes: readonly string[];
}

/** A stated hue that disagrees with the pigment it is written beside. */
function statedHueFindings(
  file: string,
  source: string,
  pattern: RegExp,
  group: number,
  hues: ReadonlyMap<string, number>,
  what: string,
): Finding[] {
  const at = createPositionResolver(source);
  const findings: Finding[] = [];
  for (const match of source.matchAll(pattern)) {
    const derived = hues.get(match[1]);
    if (derived === undefined) continue;
    const stated = Number.parseInt(match[group], 10);
    if (stated === Math.round(derived)) continue;
    findings.push({
      file,
      ...at(match.index),
      check: "area-hue-ledger",
      message:
        `${what} says pigment ${match[1]} sits at ${stated} degrees and its hex resolves to ` +
        `${derived.toFixed(1)}. The hue is derived from the pigment, so a figure written beside it is a ` +
        "second copy: correct it, or retune the pigment it describes.",
    });
  }
  return findings;
}

export async function checkAreaHues(input: HueCheckInput): Promise<HueCheckOutcome> {
  const pigmentSource = await readFile(input.pigmentFile, "utf8");
  const hues = areaHues(pigmentSource);
  const byId = new Map(hues.map((pigment) => [pigment.id, pigment.hue]));
  const findings: Finding[] = [];

  findings.push(
    ...statedHueFindings(
      input.pigmentFile,
      pigmentSource,
      COMMENTED_HUE,
      3,
      byId,
      "the pigment's own comment",
    ),
  );

  for (const sheet of input.sheetFiles) {
    const source = await readFile(sheet, "utf8");
    findings.push(
      ...statedHueFindings(sheet, source, SHEET_HUE, 2, byId, "this sheet's hardcoded ledger"),
    );
  }

  const gaps = adjacentGaps(hues);
  const tightest = gaps.toSorted((one, two) => one.gap - two.gap)[0];
  if (tightest !== undefined && tightest.gap < SEPARATION_FLOOR) {
    findings.push({
      file: input.pigmentFile,
      check: "area-hue-separation",
      message:
        `${tightest.pair} sit ${tightest.gap} degrees apart, below the ${SEPARATION_FLOOR} the ramp holds. ` +
        "Two dark colours that close stop separating at wedge scale, which is what the 07 retune was for.",
    });
  }

  const closestDealt = firstFourPairs(hues).toSorted((one, two) => one.gap - two.gap)[0];
  if (closestDealt !== undefined && closestDealt.gap < ASSIGNMENT_FLOOR) {
    findings.push({
      file: input.pigmentFile,
      check: "area-hue-assignment",
      message:
        `the first four dealt include ${closestDealt.pair} at ${closestDealt.gap} degrees, below the ` +
        `${ASSIGNMENT_FLOOR} the deal order promises. Deal a different pigment fourth, or retune one of the two.`,
    });
  }

  return {
    findings,
    notes: [
      `${hues.length} Area pigment(s), hue derived from each hex`,
      `  tightest adjacent gap ${tightest?.pair ?? "none"} at ${tightest?.gap ?? 0} degrees`,
      `  closest of the first four dealt ${closestDealt?.pair ?? "none"} at ${closestDealt?.gap ?? 0} degrees`,
    ],
  };
}

/** The layer 0 file that declares the Area pigments. */
export const pigmentFile = path.join(tokenDir, "primitives.css");
