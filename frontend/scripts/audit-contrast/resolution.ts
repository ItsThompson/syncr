/* WHAT A TOKEN CAN HOLD, ACROSS THE TOKEN LAYER AND THE SHEETS THAT DRAW.
 *
 * The ledger needs one thing from the stylesheets that no single reader gave it: the colour a name ends up as
 * where the name is not itself a colour. Three shapes make that non-trivial.
 *
 * A COMPONENT'S OWN TOKENS COUNT. Layer 2 lives beside the component that owns it, so `--grid-line-quarter-drag`
 * resolves only if the resolution reads `week-grid/tokens.css` as well as `src/tokens/`.
 *
 * A CARRIER HOLDS SEVERAL COLOURS. `--ai` is the Area identity and the class on the element decides which of
 * twelve pigments it holds, so following it is what makes those twelve measurable as the indicators they are.
 * A name that resolves to ONE colour is reported as itself, because the name a component wrote is the name a
 * reader would edit: `--ink` is `--ink`, not the ramp step it happens to sit on today.
 *
 * THREE VALUES ARE NOT A COLOUR AT ALL: `currentColor` takes whatever inherits, a gradient is a texture, and a
 * mix with transparency shows the content under it. Each is recorded with that reason rather than measured,
 * because a ratio computed for one of them would be a made-up figure. */

import { parse } from "postcss";
import { readFile } from "node:fs/promises";

import { declaredTokens } from "../lib/tokens.ts";
import { isSixDigitHex } from "../lib/contrast.ts";

/** A value no ratio can describe, with the reason it cannot. */
export interface Unmeasurable {
  readonly token: string;
  readonly value: string;
  readonly reason: string;
}

export interface Resolved {
  /** The token names this one can end up drawn as, each of which resolves to a flat colour. */
  readonly tokens: Set<string>;
  readonly unmeasurable: Unmeasurable[];
}

const TOKEN_REFERENCE = /var\((--[\w-]+)/g;

export function tokensIn(value: string): string[] {
  return [...value.matchAll(TOKEN_REFERENCE)].map((match) => match[1]);
}

/** Why this value is not a colour a ratio can be computed from, or null when it is one. */
export function whyUnmeasurable(value: string): string | null {
  const collapsed = value.trim().toLowerCase();
  if (isSixDigitHex(collapsed)) return null;
  if (collapsed === "currentcolor") return "currentColor takes whatever colour it inherits";
  if (collapsed.includes("gradient(")) return "a gradient is a texture rather than a colour";
  if (collapsed.includes("transparent")) {
    return "it carries transparency, so what shows through is the content under it";
  }
  if (/^\d/.test(collapsed)) return "it is a length or a percentage rather than a colour";
  return null;
}

/**
 * Every value each custom property can hold, across the token layer and the shipped stylesheets.
 *
 * A name maps to a SET rather than to a value, because a carrier legitimately holds several.
 */
export async function assignments(sheets: readonly string[]): Promise<Map<string, Set<string>>> {
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

/** The same findings, reported under the name a reader would edit rather than the one they resolved through. */
function renamed(found: readonly Unmeasurable[], token: string): Unmeasurable[] {
  const under: Unmeasurable[] = [];
  for (const one of found) under.push({ token, value: one.value, reason: one.reason });
  return under;
}

/** The colours a token can end up as, plus whatever about it cannot be a colour at all. */
export function coloursOf(
  held: ReadonlyMap<string, Set<string>>,
  name: string,
  seen: ReadonlySet<string> = new Set(),
): Resolved {
  if (seen.has(name)) return { tokens: new Set(), unmeasurable: [] };
  const values = held.get(name);
  if (values === undefined) return { tokens: new Set(), unmeasurable: [] };

  const walked = new Set([...seen, name]);
  if (values.size === 1) return resolvedFromOne(held, name, [...values][0], walked);

  /* Several values: a carrier. Each is followed and each is reported under its own name. */
  const tokens = new Set<string>();
  const unmeasurable: Unmeasurable[] = [];
  for (const value of values) {
    if (isSixDigitHex(value)) {
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

/** The one value a non-carrier holds, resolved to the name a reader would edit. */
function resolvedFromOne(
  held: ReadonlyMap<string, Set<string>>,
  name: string,
  value: string,
  walked: ReadonlySet<string>,
): Resolved {
  if (isSixDigitHex(value)) return { tokens: new Set([name]), unmeasurable: [] };

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

  const tokens = new Set<string>();
  const unmeasurable: Unmeasurable[] = [];
  for (const reference of referenced) {
    const followed = coloursOf(held, reference, walked);
    for (const token of followed.tokens) tokens.add(token);
    unmeasurable.push(...followed.unmeasurable);
  }
  return { tokens, unmeasurable };
}

/** The one hex a resolved token holds, following its chain when the chain does not branch. */
export function hexOf(held: ReadonlyMap<string, Set<string>>, name: string, hops = 0): string {
  const values = [...(held.get(name) ?? [])];
  const direct = values.find((value) => isSixDigitHex(value));
  if (direct !== undefined) return direct.toLowerCase();
  if (values.length === 1 && hops < 8) {
    const referenced = tokensIn(values[0]);
    if (referenced.length === 1) return hexOf(held, referenced[0], hops + 1);
  }
  throw new Error(`${name} holds no flat colour`);
}
