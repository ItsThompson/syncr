/* The kit's import zones, checked against the RESOLVED module graph.
 *
 * This exists because the oxlint-backed probe matrix cannot find a shape its own table omits. The
 * matrix derives its probes from `CAPABILITIES`, so a specifier absent from that table is never
 * crossed with any zone: the table is both the input and the oracle. Three holes reached a reviewer
 * that way, the last being `../../api/client.ts`, which the config's enumeration permitted and the
 * matrix never asked about.
 *
 * So this check takes a different input. It reads every import in the kit, RESOLVES each one against
 * the filesystem, and asks which directory under `src/` the resolved file actually lives in. A
 * specifier's spelling stops mattering: `../../api/client`, `../../api/client.ts`, `../../api/keys.js`
 * and `../../api/index` all resolve into `src/api/`, and the rule is about the directory.
 *
 * It also reports an import that resolves to nothing, which is a broken module the bundler would
 * fail on later and which no other check here would name. */

import { readFile } from "node:fs/promises";
import path from "node:path";

import { blankJsComments } from "../lib/comments.ts";
import { createPositionResolver } from "../lib/css-scan.ts";
import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { relativeToRepo } from "../lib/paths.ts";

/** Areas under `src/`, as the zone policy names them. Longest first, so `ui/domain` wins over `ui`. */
const AREAS = [
  "ui/primitives",
  "ui/layout",
  "ui/domain",
  "api",
  "app",
  "routes",
  "contract",
  "lib",
  "testing",
  "tokens",
] as const;

export type Area = (typeof AREAS)[number];

/** What each kit zone may reach, by resolved area. A package is always reachable. */
const REACHABLE: Readonly<Record<string, readonly Area[]>> = {
  "ui/primitives": ["ui/primitives", "lib", "tokens"],
  "ui/layout": ["ui/primitives", "ui/layout", "lib", "tokens"],
  "ui/domain": ["ui/primitives", "ui/layout", "ui/domain", "contract", "lib", "tokens"],
};

/* Why each area is unreachable from the kit, phrased as the capability rather than the path. */
const DENIAL_REASON: Readonly<Record<string, string>> = {
  api: "it fetches, or holds the key registry or the generated schema. Read the types from contract/",
  app: "it is the application shell and its session",
  routes: "it is a route, and a component does not know one",
  contract: "a Problem is a domain concept: a control or a container that names one is misfiled",
  testing: "it is test-only",
};

const IMPORT_SPECIFIER =
  /(?:\bfrom\s*|\bimport\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)["']([^"']+)["']/g;

/** Candidate files a specifier could resolve to, in the order a bundler would try them. */
function candidatesFor(target: string): string[] {
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

export interface CheckImportsInput {
  /** Absolute paths of the kit files to read. */
  readonly kitFiles: readonly string[];
  /** Absolute path of `src/`, which every area is named relative to. */
  readonly sourceRoot: string;
  /** Resolves a candidate path to true when a file exists there. */
  readonly exists: (candidate: string) => Promise<boolean>;
}

/** The area a resolved file belongs to, or null when it is outside every named area. */
export function areaOf(sourceRoot: string, resolved: string): Area | null {
  const relative = path.relative(sourceRoot, resolved).split(path.sep).join("/");
  return AREAS.find((area) => relative === area || relative.startsWith(`${area}/`)) ?? null;
}

export async function checkImports(input: CheckImportsInput): Promise<CheckOutcome> {
  const findings: Finding[] = [];
  let resolvedImports = 0;

  for (const file of input.kitFiles) {
    const zone = areaOf(input.sourceRoot, file);
    if (zone === null || REACHABLE[zone] === undefined) continue;

    const source = await readFile(file, "utf8");
    const at = createPositionResolver(source);
    const code = blankJsComments(source);

    for (const match of code.matchAll(IMPORT_SPECIFIER)) {
      const specifier = match[1];
      if (!specifier.startsWith(".")) continue;

      const target = path.resolve(path.dirname(file), specifier);
      const resolved = await firstExisting(candidatesFor(target), input.exists);
      if (resolved === null) {
        findings.push({
          file,
          ...at(match.index),
          check: "unresolved-import",
          message: `"${specifier}" resolves to no file. The bundler will fail on it.`,
        });
        continue;
      }

      resolvedImports += 1;
      const area = areaOf(input.sourceRoot, resolved);
      if (area === null || REACHABLE[zone].includes(area)) continue;

      findings.push({
        file,
        ...at(match.index),
        check: "import-zone",
        message:
          `"${specifier}" resolves into ${area}/, which ${zone}/ may not reach: ` +
          `${DENIAL_REASON[area] ?? "it is above this zone"}. ` +
          `Resolved to ${relativeToRepo(resolved)}.`,
      });
    }
  }

  return {
    findings,
    notes: [
      `${input.kitFiles.length} kit file(s), ${resolvedImports} relative import(s) resolved`,
      `zones checked by resolved directory: ${Object.keys(REACHABLE).join(", ")}`,
    ],
  };
}

async function firstExisting(
  candidates: readonly string[],
  exists: (candidate: string) => Promise<boolean>,
): Promise<string | null> {
  for (const candidate of candidates) {
    if (await exists(candidate)) return candidate;
  }
  return null;
}
