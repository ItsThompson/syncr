/* THE CONTRAST LEDGER: EVERY INK THE PRODUCT DRAWS WITH, AGAINST EVERY SURFACE IT FILLS WITH, COMPUTED.
 *
 * The design language's accessibility rule is not "the expected pair clears its floor". It is that a colour clears
 * it against EVERY surface it can appear on, and the reason is a measured one: `--signal-amber` clears 4.52:1 on
 * raised paper and 4.18:1 on the page, so a label in it passes on one surface and fails on the other. A pair
 * checked only where its author expected it is how amber came to have no text step at all.
 *
 * SO THE LEDGER IS THE WHOLE MATRIX, and reachability is not guessed. Which surface a given class actually sits on
 * is a fact about the DOM, which no stylesheet states and no static reading can recover; the honest alternative is
 * to measure each ink against all of them and record the verdict per cell. A cell that fails is not automatically a
 * defect -- `--on-ink` on `--paper` is 1.08:1 and could not be otherwise -- but a cell with NO RATIO is a pair
 * nobody has measured, and that is what this refuses.
 *
 * THE INKS AND THE SURFACES ARE READ OUT OF THE SHIPPED STYLESHEETS, so the matrix is the product's own palette
 * rather than a list beside it: a pigment used for the first time appears as a row the moment a component writes
 * it. That is what makes "a pair without a ratio fails the audit" enforceable rather than aspirational.
 *
 * A COMPONENT'S OWN TOKENS COUNT, AND SO DOES A CARRIER. Layer 2 lives beside the component that owns it, so the
 * resolution reads the shipped sheets' own custom properties as well as the token layer; and an ink written as a
 * CARRIER -- `border-top-color: var(--ai)`, where `--ai` is set per Area by the class on the element -- is followed
 * to the tokens the sheets assign it, so the twelve Area pigments are measured as the indicators they are rather
 * than reported as one unresolvable name.
 *
 * THREE VALUES CANNOT BE A PAIR AND SAY SO: `currentColor` takes whatever inherits, a gradient is a texture rather
 * than a colour, and the scrim is a colour mixed with transparency over arbitrary content. Each is recorded with
 * that reason rather than counted as measured, because a ratio computed for one of them would be a made-up figure.
 *
 * THE RATIOS COME FROM THE TOKEN FILES, through the same reader the plate generator uses, so a plate and a ledger
 * cannot disagree about what `--ink-deep` is. */

import { parse } from "postcss";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { filesUnder } from "../lib/files.ts";
import { appSourceDir, tokenDir } from "../lib/paths.ts";
import { declaredTokens } from "../lib/tokens.ts";

/** An indicator: a border, a rule, a dot or a glyph. WCAG's non-text floor. */
export const INDICATOR_FLOOR = 3;

/** Text, at every size this product sets. */
export const TEXT_FLOOR = 4.5;

/** Properties that put ink on a surface, and the floor each has to clear. */
const INK_PROPERTIES: Readonly<Record<string, number>> = {
  color: TEXT_FLOOR,
  "border-color": INDICATOR_FLOOR,
  "border-top-color": INDICATOR_FLOOR,
  "border-right-color": INDICATOR_FLOOR,
  "border-bottom-color": INDICATOR_FLOOR,
  "border-left-color": INDICATOR_FLOOR,
  "outline-color": INDICATOR_FLOOR,
  stroke: INDICATOR_FLOOR,
};

/** Properties that fill a surface, whose value is therefore something ink can land on. */
const SURFACE_PROPERTIES = new Set(["background", "background-color"]);

/** The page's own fill, which every surface ultimately sits on. */
const PAGE = "--paper";

const HEX = /^#[0-9a-f]{6}$/i;
const TOKEN_REFERENCE = /var\((--[\w-]+)/g;

export interface Pair {
  readonly ink: string;
  readonly surface: string;
  readonly ratio: number;
  /** The floor the strictest shipped use of this ink has to clear. */
  readonly floor: number;
  /** The declaration that set that floor, so the classification can be checked. */
  readonly floorFrom: string;
  readonly clears: boolean;
}

/** A value no ratio can describe, with the reason it cannot. */
export interface Unmeasurable {
  readonly token: string;
  readonly value: string;
  readonly reason: string;
}

export interface Ledger {
  readonly inks: readonly string[];
  readonly surfaces: readonly string[];
  readonly pairs: readonly Pair[];
  readonly unmeasurable: readonly Unmeasurable[];
  /** Every stylesheet the palette was read from, so the ledger says what it covered. */
  readonly sheets: readonly string[];
}

function tokensIn(value: string): string[] {
  return [...value.matchAll(TOKEN_REFERENCE)].map((match) => match[1]);
}

/** Why this value is not a colour a ratio can be computed from, or null when it is one. */
function whyUnmeasurable(value: string): string | null {
  const collapsed = value.trim().toLowerCase();
  if (HEX.test(collapsed)) return null;
  if (collapsed === "currentcolor") return "currentColor takes whatever colour it inherits";
  if (collapsed.includes("gradient(")) return "a gradient is a texture rather than a colour";
  if (collapsed.includes("transparent"))
    return "it carries transparency, so what shows through is the content under it";
  if (/^\d/.test(collapsed)) return "it is a length or a percentage rather than a colour";
  return null;
}

/**
 * Every value each custom property can hold, across the token layer and the shipped stylesheets.
 *
 * A name maps to a SET rather than to a value, because a carrier legitimately holds several: `--ai` is the Area
 * identity, assigned by the class on the element, and the twelve assignments are twelve pigments the same
 * declaration can draw with.
 */
async function assignments(sheets: readonly string[]): Promise<Map<string, Set<string>>> {
  const held = new Map<string, Set<string>>();
  const add = (name: string, value: string): void => {
    const values = held.get(name) ?? new Set<string>();
    values.add(value.trim());
    held.set(name, values);
  };

  for (const [name, value] of await declaredTokens()) add(name, value);
  for (const file of sheets) {
    parse(await readFile(file, "utf8")).walkDecls((declaration) => {
      if (declaration.prop.startsWith("--")) add(declaration.prop, declaration.value);
    });
  }
  return held;
}

/**
 * The colours a token can end up as, plus whatever about it cannot be a colour at all.
 *
 * A token whose chain reaches ONE colour is named by itself, because the name a component wrote is the name a
 * reader would edit: `--ink` is `--ink`, not the ramp step it happens to sit on today. A CARRIER is followed,
 * because it is not one colour: `--ai` is the Area identity and the class on the element decides which of twelve
 * pigments it holds, so the twelve are what the ledger measures.
 */
function coloursOf(
  held: ReadonlyMap<string, Set<string>>,
  name: string,
  seen: ReadonlySet<string> = new Set(),
): { readonly tokens: Set<string>; readonly unmeasurable: Unmeasurable[] } {
  if (seen.has(name)) return { tokens: new Set(), unmeasurable: [] };
  const values = held.get(name);
  if (values === undefined) return { tokens: new Set(), unmeasurable: [] };

  const walked = new Set([...seen, name]);
  if (values.size === 1) {
    const value = [...values][0];
    if (HEX.test(value)) return { tokens: new Set([name]), unmeasurable: [] };
    const referenced = tokensIn(value);
    if (referenced.length === 1 && value.trim() === `var(${referenced[0]})`) {
      /* One hop to one token: this name wears that colour, and this name is what the ledger reports. */
      const followed = coloursOf(held, referenced[0], walked);
      return {
        tokens: followed.tokens.size === 1 ? new Set([name]) : followed.tokens,
        unmeasurable: renamed(followed.unmeasurable, name),
      };
    }
    const reason = whyUnmeasurable(value);
    if (reason !== null) {
      return {
        tokens: new Set(),
        unmeasurable: [{ token: name, value: value.replace(/\s+/g, " "), reason }],
      };
    }
  }

  /* Several values, or a composed one: a carrier. Each is followed and each is reported under its own name. */
  const tokens = new Set<string>();
  const unmeasurable: Unmeasurable[] = [];
  for (const value of values) {
    if (HEX.test(value)) {
      tokens.add(name);
      continue;
    }
    const reason = whyUnmeasurable(value);
    if (reason !== null) {
      unmeasurable.push({ token: name, value: value.replace(/\s+/g, " "), reason });
      continue;
    }
    for (const reference of tokensIn(value)) {
      const followed = coloursOf(held, reference, walked);
      for (const token of followed.tokens) tokens.add(token);
      unmeasurable.push(...followed.unmeasurable);
    }
  }

  return { tokens, unmeasurable };
}

/** The same findings, reported under the name a reader would edit rather than the one they resolved through. */
function renamed(found: readonly Unmeasurable[], token: string): Unmeasurable[] {
  const under: Unmeasurable[] = [];
  for (const one of found) under.push({ token, value: one.value, reason: one.reason });
  return under;
}

interface InkUse {
  /** The strictest floor any shipped declaration puts this ink to. */
  readonly floor: number;
  /** The declaration that set it, so a reader can check the classification rather than trust it. */
  readonly where: string;
}

interface Usage {
  readonly inks: Map<string, InkUse>;
  readonly surfaces: Set<string>;
  readonly sheets: string[];
}

/* A HATCH IS A CARRIER, NOT A LABEL. `color` on a rule that also paints a hatch is what the hatch's own
 * `currentColor` reads, so the ink there is a texture at indicator weight rather than text: `.week-band` sets
 * `color: var(--forbidden-hatch-ink)` and `background-image: var(--hatch-back)` in one rule, and holding that ink to
 * the text floor would report a defect on a band nobody reads words off. */
function floorFor(property: string, rule: Set<string>): number | undefined {
  const floor = INK_PROPERTIES[property];
  if (floor === undefined) return undefined;
  if (property === "color" && rule.has("background-image")) return INDICATOR_FLOOR;
  return floor;
}

/** True for a value whose colour is a mix, which is measured where the mix percentage is known. */
function isMix(value: string): boolean {
  return value.toLowerCase().includes("color-mix(");
}

/**
 * The inks and the surfaces the shipped stylesheets actually use.
 *
 * The token layer itself is not read for USAGE: it declares every pigment, including the layer 0 ramp steps no
 * component may reference, and a ledger over the declarations would measure pairs the product cannot draw. It is
 * read for RESOLUTION, which is a different question.
 */
async function paletteInUse(sheets: readonly string[]): Promise<{
  readonly usage: Usage;
  readonly mixes: Unmeasurable[];
}> {
  const inks = new Map<string, InkUse>();
  const surfaces = new Set<string>([PAGE]);
  const mixes: Unmeasurable[] = [];

  for (const file of sheets) {
    const sheet = path.relative(appSourceDir, file);
    parse(await readFile(file, "utf8")).walkRules((rule) => {
      const properties = new Set<string>();
      rule.walkDecls((declaration) => {
        properties.add(declaration.prop.toLowerCase());
      });
      rule.walkDecls((declaration) => {
        const property = declaration.prop.toLowerCase();
        const floor = floorFor(property, properties);
        if (floor !== undefined) {
          if (isMix(declaration.value)) {
            mixes.push({
              token: `${sheet} ${rule.selector}`,
              value: declaration.value.replace(/\s+/g, " "),
              reason:
                "it is a mix, measured where its percentage is known, in the charts' own contrast ledger",
            });
            return;
          }
          for (const token of tokensIn(declaration.value)) {
            const held = inks.get(token);
            if (held === undefined || floor > held.floor) {
              inks.set(token, { floor, where: `${sheet} ${rule.selector} { ${property} }` });
            }
          }
        }
        if (SURFACE_PROPERTIES.has(property) && !isMix(declaration.value)) {
          for (const token of tokensIn(declaration.value)) surfaces.add(token);
        }
      });
    });
  }

  return {
    usage: { inks, surfaces, sheets: sheets.map((file) => path.relative(appSourceDir, file)) },
    mixes,
  };
}

function channelLuminance(channel: number): number {
  const ratio = channel / 255;
  return ratio <= 0.039_28 ? ratio / 12.92 : ((ratio + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance(hex: string): number {
  const digits = HEX.exec(hex.trim());
  if (digits === null) throw new Error(`${hex} is not a six-digit hex colour`);
  const value = Number.parseInt(digits[0].slice(1), 16);
  return (
    0.2126 * channelLuminance((value >> 16) & 0xff) +
    0.7152 * channelLuminance((value >> 8) & 0xff) +
    0.0722 * channelLuminance(value & 0xff)
  );
}

export function contrastRatio(one: string, two: string): number {
  const first = relativeLuminance(one);
  const second = relativeLuminance(two);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

/** The one hex a resolved token holds, following its chain when the chain does not branch. */
function hexOf(held: ReadonlyMap<string, Set<string>>, name: string, hops = 0): string {
  const values = [...(held.get(name) ?? [])];
  const direct = values.find((value) => HEX.test(value));
  if (direct !== undefined) return direct.toLowerCase();
  if (values.length === 1 && hops < 8) {
    const referenced = tokensIn(values[0]);
    if (referenced.length === 1) return hexOf(held, referenced[0], hops + 1);
  }
  throw new Error(`${name} holds no flat colour`);
}

/** The ledger: every ink against every surface, with the ratio each pair measures. */
export async function buildLedger(): Promise<Ledger> {
  const sheets = (await filesUnder(appSourceDir, [".css"])).filter(
    (file) => !file.startsWith(`${tokenDir}${path.sep}`),
  );
  const { usage, mixes } = await paletteInUse(sheets);
  const held = await assignments(sheets);
  const unmeasurable: Unmeasurable[] = [...mixes];

  const uses = new Map<string, InkUse>();
  for (const [token, use] of usage.inks) {
    const resolved = coloursOf(held, token);
    unmeasurable.push(...resolved.unmeasurable);
    for (const ink of resolved.tokens) {
      const carried = uses.get(ink);
      if (carried === undefined || use.floor > carried.floor) uses.set(ink, use);
    }
  }

  const surfaces = new Set<string>();
  for (const token of usage.surfaces) {
    const resolved = coloursOf(held, token);
    unmeasurable.push(...resolved.unmeasurable);
    for (const surface of resolved.tokens) surfaces.add(surface);
  }

  const inks = [...uses.keys()].toSorted();
  const surfaceNames = [...surfaces].toSorted();
  const pairs: Pair[] = [];
  for (const ink of inks) {
    const use = uses.get(ink) ?? { floor: INDICATOR_FLOOR, where: "nothing" };
    for (const surface of surfaceNames) {
      const ratio = contrastRatio(hexOf(held, ink), hexOf(held, surface));
      pairs.push({
        ink,
        surface,
        ratio,
        floor: use.floor,
        floorFrom: use.where,
        clears: ratio >= use.floor,
      });
    }
  }

  return {
    inks,
    surfaces: surfaceNames,
    pairs,
    unmeasurable: deduplicate(unmeasurable),
    sheets: usage.sheets,
  };
}

function deduplicate(found: readonly Unmeasurable[]): Unmeasurable[] {
  const byKey = new Map<string, Unmeasurable>();
  for (const one of found) byKey.set(`${one.token} ${one.value}`, one);
  return [...byKey.values()].toSorted((one, two) => one.token.localeCompare(two.token));
}
