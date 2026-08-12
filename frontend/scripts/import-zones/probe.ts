/* Running the SHIPPED oxlint config against a throwaway tree, to prove the import zones can fail.
 *
 * The fixtures are generated rather than committed, and that is forced by how the config works
 * rather than a preference: `.oxlintrc.json`'s overrides key on `src/ui/<zone>/**`, so a fixture
 * committed under `scripts/` would not be governed by the zone rules at all and a test over it
 * would pass no matter what the globs said. Materialising the tree at the real paths inside a
 * temp copy of the real config is what makes the assertion mean something.
 *
 * This exists because the import zones were the one enforcement mechanism in this frontend with no
 * fixture behind them, and they were the one with a hole. A glob that requires a path segment after
 * `domain` misses a bare barrel import, and a glob naming `ui` cannot match a relative specifier at
 * all. Both shapes are this codebase's own house style, so both were escaping. */

import { execFile } from "node:child_process";
import { copyFile, mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";

import { frontendRoot } from "../lib/paths.ts";

const run = promisify(execFile);

export type KitZone = "primitives" | "layout" | "domain";

export interface ZoneProbe {
  readonly zone: KitZone;
  /** The import specifier, written the way a component would write it. */
  readonly specifier: string;
  /** True when the zone rules must refuse it. */
  readonly isRefused: boolean;
}

export interface ZoneResult extends ZoneProbe {
  readonly wasRefused: boolean;
}

const CONFIG = ".oxlintrc.json";

/** Lints one generated file per probe and reports whether each specifier was refused. */
export async function lintZoneProbes(probes: readonly ZoneProbe[]): Promise<ZoneResult[]> {
  const root = await mkdtemp(path.join(tmpdir(), "syncr-zones-"));
  try {
    /* Copied byte for byte rather than parsed and re-serialised. The config is JSONC and carries
     * the comments explaining each zone, so `JSON.parse` cannot read it; copying also means the
     * assertion runs against the exact bytes that ship rather than against a subset of them. */
    await copyFile(path.join(frontendRoot, CONFIG), path.join(root, CONFIG));

    const names = probes.map((_, index) => `probe_${index}.ts`);
    for (const [index, probe] of probes.entries()) {
      const directory = path.join(root, "src", "ui", probe.zone);
      await mkdir(directory, { recursive: true });
      await writeFile(
        path.join(directory, names[index]),
        `import { thing } from "${probe.specifier}";\nexport const used = thing;\n`,
        "utf8",
      );
    }

    const output = await lint(root);
    const refused = refusedFiles(output);
    return probes.map((probe, index) => ({
      ...probe,
      wasRefused: refused.has(`${probe.zone}/${names[index]}`),
    }));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function lint(root: string): Promise<string> {
  const oxlint = path.join(frontendRoot, "node_modules", ".bin", "oxlint");
  const args = ["-c", path.join(root, CONFIG), "--format=json", root];
  try {
    const { stdout } = await run(oxlint, args);
    return stdout;
  } catch (cause) {
    // A non-zero exit is the expected shape when a probe is refused; the report is on the error.
    return (cause as { stdout?: string }).stdout ?? "";
  }
}

interface OxlintDiagnostic {
  readonly filename?: string;
  readonly code?: string;
}

interface OxlintReport {
  readonly diagnostics?: readonly OxlintDiagnostic[];
}

/* Parsed from oxlint's JSON rather than from its human report. The human format puts the path BEFORE
 * the rule name when stdout is not a terminal and AFTER it when it is, so a text parser silently
 * attributes each finding to the next one's file: a parser bug inside the one test whose job is to
 * prove a mechanism can fail. */
function refusedFiles(output: string): Set<string> {
  const refused = new Set<string>();
  let report: OxlintReport;
  try {
    report = JSON.parse(output) as OxlintReport;
  } catch {
    throw new Error(`oxlint produced no JSON report. Output was: ${output.slice(0, 400)}`);
  }
  if (report.diagnostics === undefined) {
    throw new Error(`oxlint's JSON report carries no diagnostics array: ${output.slice(0, 400)}`);
  }
  for (const diagnostic of report.diagnostics) {
    if (diagnostic.code === undefined || !diagnostic.code.includes("no-restricted-imports")) {
      continue;
    }
    const located = /src\/ui\/(primitives|layout|domain)\/(probe_\d+\.ts)/.exec(
      diagnostic.filename ?? "",
    );
    if (located !== null) refused.add(`${located[1]}/${located[2]}`);
  }
  return refused;
}
