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
 * TWO ESCAPES CLOSED IN ITERATION 4, both of which worked in dev, test and production:
 *
 *   A BACKTICK. `await import(`../../api/client`)` fetched, because the specifier pattern accepted
 *   single and double quotes only. So the quote style is now part of what is enumerated, and a
 *   specifier assembled by interpolation is refused outright rather than resolved, since nothing here
 *   can resolve it and it is the obvious next step from a backtick.
 *
 *   A RE-EXPORT ONE HOP AWAY. `lib/` and `contract/` are readable from the kit, and nothing
 *   constrained what THEY import, so a one-line re-export in either laundered anything. The walk is
 *   transitive now: a chain through a readable directory is followed to whatever it reaches, and the
 *   finding names the whole chain rather than the innocent-looking first hop.
 *
 * It also reports an import that resolves to nothing, which is a broken module the bundler would
 * fail on later and which no other check here would name.
 *
 * The zone model itself is in `zones.ts`: which directories exist under `src/`, what each kit zone may reach,
 * and why an area is denied. This file is the walk. */

import { readFile } from "node:fs/promises";
import path from "node:path";

import { blankJsComments } from "../lib/comments.ts";
import { createPositionResolver } from "../lib/css-scan.ts";
import type { CheckOutcome, Finding } from "../lib/findings.ts";
import { relativeToRepo } from "../lib/paths.ts";
import {
  areaOf,
  CONDUITS,
  denialReasonFor,
  isUnderSourceRoot,
  REACHABLE,
  unmodelledMessage,
  type Area,
} from "./zones.ts";

const QUOTED_SPECIFIER =
  /(?:\bfrom\s*|\bimport\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)["']([^"']+)["']/g;

/* A separate pattern, because a template literal may legally contain a quote character and so cannot
 * be folded into the one above. A backtick was the escape that reached review iteration 4. */
const TEMPLATE_SPECIFIER = /(?:\bfrom\s*|\bimport\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)`([^`]*)`/g;

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

/** A relative import as written, with where it was written. */
interface ImportSite {
  readonly specifier: string;
  readonly index: number;
  /** True when the specifier is assembled by interpolation, so no resolution is possible. */
  readonly computed: boolean;
}

/** Every relative import in a source, whatever quote style it uses. */
function importSitesIn(code: string): ImportSite[] {
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

export interface CheckImportsInput {
  /** Absolute paths of the kit files to read. */
  readonly kitFiles: readonly string[];
  /** Absolute path of `src/`, which every area is named relative to. */
  readonly sourceRoot: string;
  /** Resolves a candidate path to true when a file exists there. */
  readonly exists: (candidate: string) => Promise<boolean>;
}

/** A denied destination the walk reached, with the chain of files that got there. */
interface Denial {
  /** The area reached, or null when the resolved file's directory is not in the model. */
  readonly area: Area | null;
  readonly resolved: string;
  readonly chain: readonly string[];
}

export async function checkImports(input: CheckImportsInput): Promise<CheckOutcome> {
  const findings: Finding[] = [];
  let resolvedImports = 0;
  let modulesWalked = 0;

  const sourceOf = new Map<string, string>();
  const read = async (file: string): Promise<string> => {
    const cached = sourceOf.get(file);
    if (cached !== undefined) return cached;
    const source = blankJsComments(await readFile(file, "utf8"));
    sourceOf.set(file, source);
    return source;
  };

  const resolveFrom = async (from: string, specifier: string): Promise<string | null> =>
    firstExisting(candidatesFor(path.resolve(path.dirname(from), specifier)), input.exists);

  /**
   * Follows a chain out of a readable conduit and returns the first denied area it reaches.
   *
   * A one-line re-export in `lib/` or `contract/` is readable from every zone, and nothing else
   * checks what those files import, so this is the only thing standing between a primitive and the
   * fetch client.
   */
  const denialReachedThrough = async (
    entry: string,
    zone: string,
    seen: Set<string>,
  ): Promise<Denial | null> => {
    const queue: { file: string; chain: readonly string[] }[] = [{ file: entry, chain: [entry] }];

    while (queue.length > 0) {
      const step = queue.shift();
      if (step === undefined) break;
      if (seen.has(step.file)) continue;
      seen.add(step.file);
      modulesWalked += 1;

      for (const site of importSitesIn(await read(step.file))) {
        if (site.computed) continue;
        const resolved = await resolveFrom(step.file, site.specifier);
        if (resolved === null) continue;

        const area = areaOf(input.sourceRoot, resolved);
        const chain = [...step.chain, resolved];
        if (area === null) {
          // A package is reachable from anywhere. A directory under `src/` that the model does not
          // name is not: it is where the chain would otherwise go dark.
          if (!isUnderSourceRoot(input.sourceRoot, resolved)) continue;
          return { area: null, resolved, chain };
        }
        if (!REACHABLE[zone].includes(area)) return { area, resolved, chain };
        if (CONDUITS.includes(area)) queue.push({ file: resolved, chain });
      }
    }
    return null;
  };

  for (const file of input.kitFiles) {
    const zone = areaOf(input.sourceRoot, file);
    if (zone === null || REACHABLE[zone] === undefined) {
      /* A kit file the model gives no zone, so nothing constrains what it imports while every zone
       * may read it. Reported rather than skipped, for the same reason an unmodelled destination is. */
      findings.push({
        file,
        check: "unmodelled-zone",
        message:
          "this file is inside the kit but in no zone the model names, so no import rule applies to " +
          "it while every zone may read it. Add its directory to AREAS and give it a REACHABLE entry.",
      });
      continue;
    }

    const source = await readFile(file, "utf8");
    const at = createPositionResolver(source);
    const seen = new Set<string>([file]);

    for (const site of importSitesIn(blankJsComments(source))) {
      if (site.computed) {
        findings.push({
          file,
          ...at(site.index),
          check: "computed-import-specifier",
          message:
            `"${site.specifier}" is assembled at runtime, so no check can tell what it reaches. ` +
            "Write the specifier as a literal.",
        });
        continue;
      }

      const resolved = await resolveFrom(file, site.specifier);
      if (resolved === null) {
        findings.push({
          file,
          ...at(site.index),
          check: "unresolved-import",
          message: `"${site.specifier}" resolves to no file. The bundler will fail on it.`,
        });
        continue;
      }

      resolvedImports += 1;
      const area = areaOf(input.sourceRoot, resolved);
      if (area === null) {
        // Outside `src/` is a package, which every zone may import. Inside it, the model is silent,
        // and silence used to read as permission.
        if (!isUnderSourceRoot(input.sourceRoot, resolved)) continue;
        findings.push({
          file,
          ...at(site.index),
          check: "unmodelled-area",
          message: `"${site.specifier}" is permitted by no rule and denied by none: ${unmodelledMessage(resolved)}`,
        });
        continue;
      }

      if (!REACHABLE[zone].includes(area)) {
        findings.push({
          file,
          ...at(site.index),
          check: "import-zone",
          message:
            `"${site.specifier}" resolves into ${area}/, which ${zone}/ may not reach: ` +
            `${denialReasonFor(area)}. ` +
            `Resolved to ${relativeToRepo(resolved)}.`,
        });
        continue;
      }

      /* The first hop is permitted. Follow it anyway when it lands in a conduit, because permitted is
       * not the same as harmless: `lib/` re-exporting the fetch client is how a primitive fetches
       * without ever naming `api/`. */
      if (!CONDUITS.includes(area)) continue;
      const laundered = await denialReachedThrough(resolved, zone, seen);
      if (laundered === null) continue;

      findings.push({
        file,
        ...at(site.index),
        check: "import-zone-through-chain",
        message:
          laundered.area === null
            ? `"${site.specifier}" is permitted, but the chain leaves the model: ` +
              `${unmodelledMessage(laundered.resolved)} Chain: ` +
              `${laundered.chain.map((step) => relativeToRepo(step)).join(" -> ")}.`
            : `"${site.specifier}" is permitted, but it reaches ${laundered.area}/, which ${zone}/ ` +
              `may not: ${denialReasonFor(laundered.area)}. Chain: ` +
              `${laundered.chain.map((step) => relativeToRepo(step)).join(" -> ")}.`,
      });
    }
  }

  return {
    findings,
    notes: [
      `${input.kitFiles.length} kit file(s), ${resolvedImports} relative import(s) resolved`,
      `zones checked by resolved directory: ${Object.keys(REACHABLE).join(", ")}`,
      `${modulesWalked} module(s) walked past the first hop, through ${CONDUITS.join(", ")}`,
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
