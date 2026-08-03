/* THE KIT'S ZONE MODEL: which directories exist under `src/`, and what each kit zone may reach.
 *
 * It is a model rather than a list of the directories that existed the day it was written, and the
 * difference is the whole point. `AREAS` was that list once, so a directory nobody had added to it read as
 * permitted AND stopped the transitive walk: `src/shared/plumbing.ts` re-exporting the fetch client let a
 * `ui/domain` component fetch in dev, in test and in production with every check green. A directory the model
 * does not name is now a finding of its own, which is the same choice `scripts/import-zones/policy.ts` makes
 * when it throws on a specifier that names no capability.
 *
 * A file OUTSIDE `src/` is a package, and a package is reachable from anywhere. Telling that apart from an
 * unmodelled directory is what `isUnderSourceRoot` is for: one null meant both, and both were permitted. */

import path from "node:path";

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
  "assets",
] as const;

export type Area = (typeof AREAS)[number];

/** What each kit zone may reach, by resolved area. A package is always reachable. */
export const REACHABLE: Readonly<Record<string, readonly Area[]>> = {
  "ui/primitives": ["ui/primitives", "lib", "tokens"],
  "ui/layout": ["ui/primitives", "ui/layout", "lib", "tokens"],
  "ui/domain": ["ui/primitives", "ui/layout", "ui/domain", "contract", "lib", "tokens", "assets"],
};

/* Why each area is unreachable from the kit, phrased as the capability rather than the path. */
const DENIAL_REASON: Readonly<Record<string, string>> = {
  api: "it fetches, or holds the key registry or the generated schema. Read the types from contract/",
  app: "it is the application shell and its session",
  routes: "it is a route, and a component does not know one",
  contract: "a Problem is a domain concept: a control or a container that names one is misfiled",
  testing: "it is test-only",
  assets:
    "an asset is committed content, and placing it is a domain decision: the illustration plates are " +
    "the only ones, they are never behind data, and a control or a container that reached for one " +
    "would be drawing ornament into a surface the design language keeps clear",
};

/**
 * Areas a kit zone may read that are NOT themselves kit zones, so nothing else checks what they import.
 *
 * A chain is followed through these, and only these: a kit file reached in a chain is checked directly on its
 * own turn, so following it would report the same violation twice.
 */
export const CONDUITS: readonly Area[] = ["lib", "contract", "tokens"];

/**
 * Areas that are the end of a chain, because nothing in them imports anything.
 *
 * `assets` holds committed binary plates. A chain cannot be laundered through a PNG, so following one would be
 * reading an image as source. Every non-kit area a zone may reach is either a conduit or a leaf, and the zone
 * test asserts that, so a directory added to `REACHABLE` has to be classified as one or the other rather than
 * quietly becoming a hole the walk stops at.
 */
export const LEAVES: readonly Area[] = ["assets"];

/** The area a resolved file belongs to, or null when it is outside every named area. */
export function areaOf(sourceRoot: string, resolved: string): Area | null {
  const relative = path.relative(sourceRoot, resolved).split(path.sep).join("/");
  return AREAS.find((area) => relative === area || relative.startsWith(`${area}/`)) ?? null;
}

/**
 * True when a resolved file sits inside `src/`, which is what makes an unnamed area a finding.
 *
 * A file outside `src/` is a package, and a package is always reachable. Telling the two apart is the whole of
 * the fix: `areaOf` returning null meant both, and both were treated as permitted.
 */
export function isUnderSourceRoot(sourceRoot: string, resolved: string): boolean {
  const relative = path.relative(sourceRoot, resolved);
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}

/** Why an area a kit zone reached is denied to it. */
export function denialReasonFor(area: Area): string {
  return DENIAL_REASON[area] ?? "it is above this zone";
}

/** What the model says about a directory it does not name. Denied, and it says so as a finding. */
export function unmodelledMessage(resolved: string): string {
  return (
    `it resolves to ${relativeToRepo(resolved)}, which sits under src/ in a directory the zone ` +
    "model does not name, so no rule here can say what it may reach. Add the directory to AREAS and " +
    "to REACHABLE in scripts/check-imports/zones.ts, and to the glob groups in .oxlintrc.json. A " +
    "directory nobody modelled is how a primitive came to reach the fetch client through " +
    "src/shared/ with every check green."
  );
}
