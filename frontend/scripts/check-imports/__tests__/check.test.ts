/* The kit's import zones, checked against the resolved module graph.
 *
 * The fixture tree is a miniature `src/` with a real `api/`, `app/`, `routes/`, `contract/` and
 * `lib/`, because this check RESOLVES rather than pattern-matches: it has to find files on disk. The
 * `Smuggler` fixture is the component review iteration 3 built, which passed tsc, oxlint, prettier
 * and vite build, in every spelling of the same capability. */

import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { filesUnder } from "../../lib/files.ts";
import { areaOf, checkImports, isUnderSourceRoot } from "../check.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const sourceRoot = path.join(here, "..", "__fixtures__", "src");

const exists = async (candidate: string): Promise<boolean> => {
  try {
    return (await stat(candidate)).isFile();
  } catch {
    return false;
  }
};

const check = async (relativeFiles: string[]) =>
  checkImports({
    kitFiles: relativeFiles.map((file) => path.join(sourceRoot, file)),
    sourceRoot,
    exists,
  });

const messagesFor = (findings: readonly { check: string; message: string }[], rule: string) =>
  findings.filter((finding) => finding.check === rule).map((finding) => finding.message);

describe("a fetching kit component", () => {
  it("is caught in every spelling of the capability", async () => {
    const outcome = await check(["ui/domain/shell/Smuggler.ts"]);
    const zones = messagesFor(outcome.findings, "import-zone");

    expect(zones).toHaveLength(6);
  });

  it.each([
    ["../../../api/client.ts", "api/"],
    ["../../../api/keys.js", "api/"],
    ["../../../api/index", "api/"],
    ["../../../api/schema", "api/"],
    ["../../../app/signIn", "app/"],
    ["../../../routes", "routes/"],
  ])("catches %s, resolving into %s", async (specifier, area) => {
    const outcome = await check(["ui/domain/shell/Smuggler.ts"]);
    const message = messagesFor(outcome.findings, "import-zone").find((text) =>
      text.startsWith(`"${specifier}"`),
    );

    expect(message).toContain(`resolves into ${area}`);
  });

  it("names the capability rather than the path, so the reason survives a rename", async () => {
    const outcome = await check(["ui/domain/shell/Smuggler.ts"]);
    const client = messagesFor(outcome.findings, "import-zone").find((text) =>
      text.includes("api/client.ts"),
    );

    expect(client).toContain("it fetches");
    expect(client).toContain("Read the types from contract/");
  });
});

describe("a compliant kit component", () => {
  it("produces no finding", async () => {
    const outcome = await check(["ui/domain/shell/Legal.ts"]);
    expect(outcome.findings).toEqual([]);
  });

  it("counts what it resolved, so a check that read nothing is visible", async () => {
    const outcome = await check(["ui/domain/shell/Legal.ts"]);
    expect(outcome.notes[0]).toContain("4 relative import(s) resolved");
  });
});

describe("the lower zones", () => {
  it("refuses a primitive reaching a layer above it and a domain type", async () => {
    const outcome = await check(["ui/primitives/Overreaching.ts"]);
    const zones = messagesFor(outcome.findings, "import-zone");

    expect(zones).toHaveLength(2);
    expect(zones.some((text) => text.includes("ui/layout/"))).toBe(true);
    expect(zones.some((text) => text.includes("misfiled"))).toBe(true);
  });
});

describe("an import that resolves to nothing", () => {
  it("is reported, because the bundler would fail on it later", async () => {
    const outcome = await check(["ui/layout/Broken.ts"]);

    expect(messagesFor(outcome.findings, "unresolved-import")).toEqual([
      '"./Vanished" resolves to no file. The bundler will fail on it.',
    ]);
  });
});

/* THE TWO ESCAPES THAT REACHED REVIEW ITERATION 4. Both worked in dev, in test and in production, and
 * one of them moved `vite build` from 118 to 119 modules with the fetch code in the chunk. */
describe("a backtick-quoted specifier", () => {
  it("is caught, because the quote style is not the rule", async () => {
    const outcome = await check(["ui/primitives/Backtick.ts"]);
    const zones = messagesFor(outcome.findings, "import-zone");

    expect(zones).toHaveLength(1);
    expect(zones[0]).toContain("resolves into api/");
    expect(zones[0]).toContain("it fetches");
  });
});

describe("a specifier assembled at runtime", () => {
  it("is refused rather than ignored, since nothing can tell what it reaches", async () => {
    const outcome = await check(["ui/primitives/Computed.ts"]);

    expect(messagesFor(outcome.findings, "computed-import-specifier")).toEqual([
      '"../../api/${part}" is assembled at runtime, so no check can tell what it reaches. ' +
        "Write the specifier as a literal.",
    ]);
  });
});

describe("a re-export in a directory every zone may read", () => {
  it("is caught one hop past the permitted first hop", async () => {
    const outcome = await check(["ui/primitives/Laundered.ts"]);
    const chains = messagesFor(outcome.findings, "import-zone-through-chain");

    expect(chains).toHaveLength(1);
    expect(chains[0]).toContain('"../../lib/handy.ts" is permitted, but it reaches api/');
  });

  it("names the whole chain, not the innocent first hop", async () => {
    const outcome = await check(["ui/primitives/Laundered.ts"]);
    const chain = messagesFor(outcome.findings, "import-zone-through-chain")[0];

    expect(chain).toContain("lib/handy.ts -> ");
    expect(chain).toContain("api/client.ts");
  });

  it("follows more than one hop", async () => {
    const outcome = await check(["ui/primitives/DeepLaundered.ts"]);
    const chains = messagesFor(outcome.findings, "import-zone-through-chain");

    expect(chains).toHaveLength(1);
    expect(chains[0]).toContain("lib/deep.ts -> ");
    expect(chains[0]).toContain("lib/handy.ts -> ");
    expect(chains[0]).toContain("api/client.ts");
  });

  /* A walk without a visited set spins forever on this, and the timeout would look like a hang rather
   * than a bug. The cycle is legal and must stay clean. */
  it("terminates on an import cycle and reports nothing for it", async () => {
    const outcome = await check(["ui/primitives/DeepLaundered.ts"]);
    const cycle = messagesFor(outcome.findings, "import-zone-through-chain").filter((text) =>
      text.includes("loop-"),
    );

    expect(cycle).toEqual([]);
  });

  it("reports how far past the first hop it walked", async () => {
    const outcome = await check(["ui/primitives/DeepLaundered.ts"]);

    expect(outcome.notes[2]).toMatch(/[1-9]\d* module\(s\) walked past the first hop/);
    expect(outcome.notes[2]).toContain("lib, contract, tokens");
  });

  it("leaves a conduit that reaches nothing denied alone", async () => {
    const outcome = await check(["ui/domain/shell/Legal.ts"]);
    expect(outcome.findings).toEqual([]);
  });
});

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

/* NULL FROM `areaOf` MEANT TWO THINGS AND WAS TREATED AS ONE. A package is always reachable; a
 * directory under `src/` that nobody modelled is not, and treating the second as permitted let a kit
 * component fetch through `src/shared/` with every check green. These are the tests for the
 * distinction. */
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

describe("a directory the zone model does not name", () => {
  it("is a finding rather than a silent permission", async () => {
    const outcome = await check(["ui/domain/shell/Unmodelled.ts"]);
    const unmodelled = messagesFor(outcome.findings, "unmodelled-area");

    expect(unmodelled).toHaveLength(1);
    expect(unmodelled[0]).toContain('"../../../shared/plumbing.ts"');
    expect(unmodelled[0]).toContain("shared/plumbing.ts");
  });

  it("says what to do about it, naming both halves of the model", async () => {
    const outcome = await check(["ui/domain/shell/Unmodelled.ts"]);

    expect(messagesFor(outcome.findings, "unmodelled-area")[0]).toContain("AREAS");
    expect(messagesFor(outcome.findings, "unmodelled-area")[0]).toContain(".oxlintrc.json");
  });

  it("does not report a package, which every zone may import", async () => {
    const outcome = await check(["ui/domain/shell/Legal.ts"]);

    expect(outcome.findings).toEqual([]);
  });

  it("stops a chain from going dark, so a hop into it is named with the whole chain", async () => {
    const outcome = await check(["ui/primitives/LaunderedThroughUnmodelled.ts"]);
    const chains = messagesFor(outcome.findings, "import-zone-through-chain");

    expect(chains).toHaveLength(1);
    expect(chains[0]).toContain("the chain leaves the model");
    expect(chains[0]).toContain("lib/via-unmodelled.ts -> ");
    expect(chains[0]).toContain("shared/plumbing.ts");
  });
});

describe("a kit file in no zone", () => {
  it("is reported, because nothing constrains it while every zone may read it", async () => {
    const outcome = await check(["ui/rogue.ts"]);
    const zones = messagesFor(outcome.findings, "unmodelled-zone");

    expect(zones).toHaveLength(1);
    expect(zones[0]).toContain("no zone the model names");
  });
});

describe("the check's own coverage", () => {
  /* The point of this check is that its input is the filesystem rather than a table of specifier
   * spellings, so it sees every kit file whether or not anything anticipated the shape. */
  it("reads every kit file in the fixture tree", async () => {
    const kitFiles = (await filesUnder(path.join(sourceRoot, "ui"), [".ts", ".tsx"])).filter(
      (file) => !file.includes(".test."),
    );

    expect(kitFiles.length).toBeGreaterThanOrEqual(4);

    const outcome = await checkImports({ kitFiles, sourceRoot, exists });
    expect(outcome.notes[0]).toContain(`${kitFiles.length} kit file(s)`);
  });
});
