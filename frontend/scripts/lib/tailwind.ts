/* Compiling utilities with Tailwind's own compiler, and attributing each emitted declaration to the
 * candidate that produced it.
 *
 * WHY A COMPILER AND NOT A PATTERN. Four times in these checks, a check matched on syntax the author
 * had thought of and missed a spelling the language permits: a glob that missed a barrel import, a
 * regex that missed `-rotate-3`, a tokenizer that destroyed `[color:red]`, and two arbitrary-value
 * patterns written around `[` that were blind to Tailwind's `(--var)` form. Each fix added a pattern
 * and the next spelling walked through.
 *
 * The declarations a utility EMITS are not a spelling. `blur-(--haze)`, `blur-[3px]` and
 * `@apply blur-sm` all emit `filter`, so a verdict derived from the emitted CSS is immune to however
 * Tailwind spells the input next.
 *
 * ONE GOTCHA, AND IT IS THE REASON THIS MODULE EXISTS RATHER THAN A ONE-LINER AT EACH CALL SITE:
 * a compiler instance ACCUMULATES candidates across `build()` calls, so `build(["a"])` then
 * `build(["b"])` returns the CSS for both and attributing by position silently reports a's
 * declarations for b. The first draft of this check did exactly that and reported
 * `--tw-shadow: var(--halo)` for `shadow-sm`. Candidates are compiled in one call and attributed by
 * escaped selector. */

import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { compile } from "tailwindcss";

const require = createRequire(import.meta.url);

export type Declaration = readonly [property: string, value: string];

/** Maps each candidate to the declarations it emits. A candidate that compiles to nothing maps to []. */
export type EmittedDeclarations = ReadonlyMap<string, readonly Declaration[]>;

async function loadStylesheet(id: string, base: string) {
  const target = id.startsWith(".")
    ? path.resolve(base, id)
    : require.resolve(id === "tailwindcss" ? "tailwindcss/index.css" : id, { paths: [base] });
  return { path: target, base: path.dirname(target), content: await readFile(target, "utf8") };
}

/* Tailwind escapes a class name's punctuation with a backslash to make a valid selector. Reproducing
 * that escape is how a rule is attributed back to the candidate that produced it. */
const NEEDS_ESCAPE = /[[\](){}:.,#%!/\\<>*+~='"?]/g;

function selectorFor(candidate: string): string {
  return `.${candidate.replace(NEEDS_ESCAPE, (character) => `\\${character}`)}`;
}

/** Leaf rules only: a block whose body contains no brace, so an at-rule wrapper is skipped. */
const LEAF_RULE = /([^{}]+)\{([^{}]*)\}/g;

/* Split rather than matched. A regex for a property name has to decide whether the name may start
 * with a dash, and the first draft required one: it read `background-color` as `-color` and dropped
 * `width` entirely, so every rule with only normal properties vanished and half the candidates looked
 * like they compiled to nothing. Splitting on `;` and then on the FIRST colon cannot make that
 * mistake. */
function declarationsIn(body: string): Declaration[] {
  const declarations: Declaration[] = [];
  for (const statement of body.split(";")) {
    const colon = statement.indexOf(":");
    if (colon < 0) continue;
    const property = statement.slice(0, colon).trim();
    const value = statement
      .slice(colon + 1)
      .replace(/\s+/g, " ")
      .trim();
    if (property !== "" && value !== "") declarations.push([property, value]);
  }
  return declarations;
}

/**
 * Compiles `theme.css` once and returns what each candidate emits.
 *
 * Compiling the theme is the expensive step, so it happens once for the whole set.
 */
export async function emittedDeclarationsFor(
  srcDir: string,
  candidates: readonly string[],
): Promise<EmittedDeclarations> {
  const emitted = new Map<string, readonly Declaration[]>();
  if (candidates.length === 0) return emitted;

  const css = await readFile(path.join(srcDir, "theme.css"), "utf8");
  const compiler = await compile(css, { base: srcDir, loadStylesheet });

  const unique = [...new Set(candidates)];
  const out = compiler.build(unique);
  const layerAt = out.indexOf("@layer utilities");
  const layer = layerAt < 0 ? "" : out.slice(layerAt);

  const rules: { selector: string; declarations: Declaration[] }[] = [];
  for (const match of layer.matchAll(LEAF_RULE)) {
    const declarations = declarationsIn(match[2]);
    if (declarations.length > 0) rules.push({ selector: match[1].trim(), declarations });
  }

  for (const candidate of unique) {
    const selector = selectorFor(candidate);
    const own = rules.filter((rule) => rule.selector.includes(selector));
    emitted.set(
      candidate,
      own.flatMap((rule) => rule.declarations),
    );
  }
  return emitted;
}
