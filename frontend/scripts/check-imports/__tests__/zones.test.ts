/* THE ZONE MODEL, ON ITS OWN.
 *
 * `__tests__/check.test.ts` drives the walk over a fixture tree, which is where "does this import get
 * caught" belongs. These cases are the model underneath it: which directory a resolved file belongs to,
 * whether a file is source the model is responsible for at all, and whether a denial says something a reader
 * can act on.
 *
 * NULL FROM `areaOf` MEANT TWO THINGS AND WAS TREATED AS ONE. A package is always reachable; a directory
 * under `src/` that nobody modelled is not, and treating the second as permitted let a kit component fetch
 * through `src/shared/` with every check green. The distinction is the reason this module exists. */

import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  areaOf,
  CONDUITS,
  denialReasonFor,
  isUnderSourceRoot,
  LEAVES,
  REACHABLE,
  unmodelledMessage,
  type Area,
} from "../zones.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourceRoot = path.join(here, "..", "__fixtures__", "src");

describe("areaOf", () => {
  it.each([
    ["ui/domain/shell/TopBar.tsx", "ui/domain"],
    ["ui/primitives/Button.tsx", "ui/primitives"],
    ["api/client.ts", "api"],
    ["contract/problem.ts", "contract"],
    ["tokens/index.css", "tokens"],
  ])("maps %s to %s", (relative, area) => {
    expect(areaOf(sourceRoot, path.join(sourceRoot, relative))).toBe(area);
  });

  it("returns null for a file outside every named area", () => {
    expect(areaOf(sourceRoot, path.join(sourceRoot, "main.tsx"))).toBeNull();
  });

  it("does not read a sibling directory as an area by prefix", () => {
    expect(areaOf(sourceRoot, path.join(sourceRoot, "apiary", "thing.ts"))).toBeNull();
  });
});

describe("isUnderSourceRoot", () => {
  it.each(["shared/plumbing.ts", "main.tsx", "ui/primitives/Button.tsx"])(
    "reads %s as source the model is responsible for",
    (relative) => {
      expect(isUnderSourceRoot(sourceRoot, path.join(sourceRoot, relative))).toBe(true);
    },
  );

  it.each(["../package.json", "../../node_modules/react/index.js"])(
    "reads %s as outside src, which is a package and always reachable",
    (relative) => {
      expect(isUnderSourceRoot(sourceRoot, path.join(sourceRoot, relative))).toBe(false);
    },
  );

  it("does not read src itself as a file under src", () => {
    expect(isUnderSourceRoot(sourceRoot, sourceRoot)).toBe(false);
  });
});

/** The areas no kit zone may reach, each with the words its denial has to carry. */
const DENIALS: readonly (readonly [Area, string])[] = [
  ["api", "fetches"],
  ["app", "shell"],
  ["routes", "route"],
  ["testing", "test-only"],
];

describe("what the model says when it denies something", () => {
  it.each(DENIALS)("says why %s is denied, as a capability rather than a path", (area, phrase) => {
    expect(denialReasonFor(area)).toContain(phrase);
  });

  it("denies every one of them to every kit zone, so the reasons are not decoration", () => {
    const reachable = new Set(Object.values(REACHABLE).flat());

    expect(DENIALS.map(([area]) => area).filter((area) => reachable.has(area))).toEqual([]);
  });
  /* A finding that says "denied" and stops is a finding a reader cannot act on. This one has to name both
   * halves of the model, because adding a directory means editing both, and the oxlint globs as well. */
  it("tells an author every place an unmodelled directory has to be added", () => {
    const message = unmodelledMessage(path.join(sourceRoot, "shared", "plumbing.ts"));

    expect(message).toContain("AREAS");
    expect(message).toContain("REACHABLE");
    expect(message).toContain("scripts/check-imports/zones.ts");
    expect(message).toContain(".oxlintrc.json");
  });
});

describe("the conduits a chain is followed through", () => {
  /* A conduit is an area a kit zone may read and no other check constrains, which is exactly the shape a
   * one-line re-export laundered an import through. Every non-kit area any zone may reach is either a conduit or
   * a LEAF: `contract` is readable from `ui/domain` alone and is still a conduit, because that is the zone that
   * can launder through it, while `assets` holds binary plates that import nothing and end a chain. A kit zone is
   * neither, since it is checked on its own turn. */
  it("holds every non-kit area a kit zone may reach, as a conduit or a leaf", () => {
    const reachable = new Set(Object.values(REACHABLE).flat());
    const nonKit = [...reachable].filter((area) => !area.startsWith("ui/"));

    expect(nonKit.toSorted()).toEqual([...CONDUITS, ...LEAVES].toSorted());
    expect(CONDUITS.filter((area) => area.startsWith("ui/"))).toEqual([]);
    expect(CONDUITS.filter((area) => LEAVES.includes(area))).toEqual([]);
  });
});
