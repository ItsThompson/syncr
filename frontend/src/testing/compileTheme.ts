/* Compiling `theme.css` the way the build does, so a test can assert what a utility becomes.
 *
 * Tailwind's own compiler is used rather than a parsed copy of the theme, because the question
 * these tests ask is what the BUILD emits: a theme entry that never reaches a utility, or a
 * stock name that survives a cleared namespace, is invisible to any check that reads the source. */

import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { compile } from "tailwindcss";

const require = createRequire(import.meta.url);

export const srcDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

async function loadStylesheet(id: string, base: string) {
  const target = id.startsWith(".")
    ? path.resolve(base, id)
    : require.resolve(id === "tailwindcss" ? "tailwindcss/index.css" : id, { paths: [base] });
  return { path: target, base: path.dirname(target), content: await readFile(target, "utf8") };
}

/** Compiles `theme.css` and returns the CSS the given utility class names produce. */
export async function compileUtilities(candidates: readonly string[]): Promise<string> {
  const css = await readFile(path.join(srcDir, "theme.css"), "utf8");
  const compiled = await compile(css, { base: srcDir, loadStylesheet });
  return compiled.build([...candidates]);
}

/** The declaration block of one compiled utility, or null when the class produced nothing. */
export function declarationsOf(css: string, className: string): string | null {
  const escaped = className.replace(/[.:[\]\\]/g, (character) => `\\\\?${character}`);
  const match = new RegExp(`\\.${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  return match === null ? null : match[1].trim();
}
