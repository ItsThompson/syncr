/* HOW A RELATIVE IMPORT IS FOUND AND RESOLVED, in one place.
 *
 * Two checks need the module graph and they need it for different questions. `check-imports` asks which
 * directory a resolved file lives in, so a kit zone cannot reach above itself. `validate-tokens` asks which
 * stylesheets a component actually loads, so a `var()` reference can be resolved against the cascade that reaches
 * a browser rather than against every sheet in the tree.
 *
 * The extraction matters because the escapes are in the FINDING, not in the walking. A backtick specifier reached
 * review iteration 4 of the primitives layer, and a `.js` specifier resolving to a `.ts` file reached the one
 * before it. A second copy of these patterns in a second check would be a second chance to miss the same shape. */

import path from "node:path";

const QUOTED_SPECIFIER =
  /(?:\bfrom\s*|\bimport\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)["']([^"']+)["']/g;

/* A separate pattern, because a template literal may legally contain a quote character and so cannot
 * be folded into the one above. A backtick was the escape that reached review iteration 4. */
const TEMPLATE_SPECIFIER = /(?:\bfrom\s*|\bimport\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)`([^`]*)`/g;

/** A relative import as written, with where it was written. */
export interface ImportSite {
  readonly specifier: string;
  readonly index: number;
  /** True when the specifier is assembled by interpolation, so no resolution is possible. */
  readonly computed: boolean;
}

/** Every relative import in a source, whatever quote style it uses. */
export function importSitesIn(code: string): ImportSite[] {
  const sites: ImportSite[] = [];
  for (const match of code.matchAll(QUOTED_SPECIFIER)) {
    sites.push({ specifier: match[1], index: match.index, computed: false });
  }
  for (const match of code.matchAll(TEMPLATE_SPECIFIER)) {
    sites.push({ specifier: match[1], index: match.index, computed: match[1].includes("${") });
  }
  return sites
    .filter((site) => site.specifier.startsWith("."))
    .toSorted((left, right) => left.index - right.index);
}

/** Candidate files a specifier could resolve to, in the order a bundler would try them. */
export function candidatesFor(target: string): string[] {
  // A `.js` specifier resolving to a `.ts` file is `moduleResolution: bundler` behaviour and needs
  // no compiler flag, and `.d.ts` is how the generated schema is spelled on disk. Both were shapes
  // an earlier enumeration missed, so both are resolved here rather than assumed away.
  const withoutJs = target.replace(/\.js$/, "");
  return [
    target,
    `${target}.ts`,
    `${target}.tsx`,
    `${target}.d.ts`,
    `${target}.css`,
    `${withoutJs}.ts`,
    `${withoutJs}.tsx`,
    path.join(target, "index.ts"),
    path.join(target, "index.tsx"),
  ];
}

/** True when a file exists at the candidate path. */
export type Exists = (candidate: string) => Promise<boolean>;

/** The first candidate that exists, or null when a specifier resolves to nothing. */
export async function firstExisting(
  candidates: readonly string[],
  exists: Exists,
): Promise<string | null> {
  for (const candidate of candidates) {
    if (await exists(candidate)) return candidate;
  }
  return null;
}

/** Where a specifier written in `from` resolves to, or null when nothing is there. */
export function resolveSpecifier(
  from: string,
  specifier: string,
  exists: Exists,
): Promise<string | null> {
  return firstExisting(candidatesFor(path.resolve(path.dirname(from), specifier)), exists);
}
