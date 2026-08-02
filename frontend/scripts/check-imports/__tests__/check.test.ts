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
import { areaOf, checkImports } from "../check.ts";

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
