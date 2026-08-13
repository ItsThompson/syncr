/* THE CHARACTER LEDGER, AND THE TOKENS EVERY THRESHOLD IN IT WAS WORKED BACK FROM.
 *
 * The width policy's floor is 17 characters per day column and every breakpoint is derived from it rather than
 * chosen, so a test that asserts a threshold does the same arithmetic. Two suites ask that question -- the grid's
 * own width policy and where the detail panel mounts -- and a second copy of these figures would let one of them
 * keep passing against a retuned sidebar, a retuned rail or a changed face.
 *
 * THE ADVANCE IS THE ONE FIGURE HELD AGAINST NOTHING. It comes from the design record's own character ledger,
 * measured in JetBrains Mono at 11.5px, and a change of face or of --fs-block would move it silently. Everything
 * else here is read from the file that declares it. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { parse } from "postcss";

import { srcDir } from "./compileTheme";

/** The measured advance of one character at --fs-block in the mono face. */
export const CHARACTER_PX = 7.02;

export const CHARACTER_FLOOR = 17;

/* What a day column loses to the block's own chrome before a character fits: the 1px inset either side, the 3px
 * state rule, and --block-pad-x either side. The ledger in the design record works backwards through exactly
 * these. */
export const CHROME_PX = 2 * 1 + 3 + 2 * 5;

/** The declared value of a layer 1 token, read from the file that declares it. */
export async function layoutToken(property: string): Promise<string> {
  const source = await readFile(path.join(srcDir, "tokens", "layout.css"), "utf8");
  let found: string | null = null;
  parse(source).walkDecls((declaration) => {
    if (declaration.prop === property) found = declaration.value.trim();
  });
  if (found === null) throw new Error(`layout.css declares no ${property}`);
  return found;
}

/** The same token as a figure, following the one level of indirection a length token legitimately takes. */
export async function layoutPixels(property: string): Promise<number> {
  const value = await layoutToken(property);
  /* One level is followed because a token legitimately names another: the closed panel's width IS one control
   * height rather than a length that happens to equal one. */
  const reference = /^var\((--[\w-]+)\)$/.exec(value);
  return Number.parseFloat(reference === null ? value : await layoutToken(reference[1]));
}
