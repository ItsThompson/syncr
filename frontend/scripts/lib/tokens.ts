/* THE TOKEN LAYER, READ AS VALUES.
 *
 * Two very different consumers need the same thing: what a semantic token actually resolves to. The contrast
 * ledgers need it to compute a ratio from the pigments that ship, and the plate generator needs it to bake a
 * plate in the ink the product draws with rather than in a hex somebody chose. One reader, so a plate and a
 * ledger cannot disagree about what --ink-deep is.
 *
 * Comments are dropped by `scanCss`, which matters: the token files explain themselves at length, and a
 * declaration inside a comment is prose rather than a value. */

import { readFile } from "node:fs/promises";
import path from "node:path";

import { scanCss } from "./css-scan.ts";
import { tokenDir } from "./paths.ts";

const TOKEN_FILES = ["primitives.css", "color.css", "layout.css", "type.css"];

/** Every custom property the layer declares, by name. */
export async function declaredTokens(): Promise<Map<string, string>> {
  const tokens = new Map<string, string>();
  for (const file of TOKEN_FILES) {
    const scan = scanCss(await readFile(path.join(tokenDir, file), "utf8"));
    for (const declaration of scan.declarations) tokens.set(declaration.name, declaration.value);
  }
  return tokens;
}

/** Resolves a token through however many `var()` hops it takes to reach a literal. */
export function resolveToken(tokens: ReadonlyMap<string, string>, name: string): string {
  let value = tokens.get(name);
  for (let hop = 0; hop < 8 && value !== undefined; hop += 1) {
    const reference = /^var\((--[\w-]+)\)$/.exec(value.trim());
    if (reference === null) return value.trim();
    value = tokens.get(reference[1]);
  }
  throw new Error(`${name} does not resolve to a literal`);
}

/** The six-digit hex a colour token resolves to. */
export async function resolveColourToken(name: string): Promise<string> {
  const literal = resolveToken(await declaredTokens(), name);
  if (!/^#[0-9a-f]{6}$/i.test(literal)) {
    throw new Error(`${name} resolves to ${literal}, which is not a six-digit hex colour`);
  }
  return literal.toLowerCase();
}
