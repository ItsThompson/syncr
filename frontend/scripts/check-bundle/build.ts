/* Building the application in memory, so the gate reads the artifact rather than a stale `dist/`.
 *
 * `write: false` is deliberate: a check must not leave build output behind, and reading a `dist/`
 * somebody else produced would make the gate's verdict depend on when that build ran. Vite resolves
 * `vite.config.ts` itself, so this compiles through the same plugin chain a deploy does.
 *
 * The barrel probes compile through that chain too, from an entry that exists only for the length of
 * the build: a probe file in the tree would be scanned by every other check as if a screen wrote it. */

import path from "node:path";
import { build, type InlineConfig, type Plugin } from "vite";

import { BARREL_PROBES, type BarrelPayload, type BarrelProbe } from "./barrels.ts";
import { frontendRoot } from "../lib/paths.ts";
import type { BuiltStylesheet } from "./check.ts";

interface EmittedAsset {
  readonly name: string;
  readonly css: string;
}

async function emittedStylesheets(config: InlineConfig): Promise<EmittedAsset[]> {
  const result = await build(config);

  const outputs = Array.isArray(result) ? result : [result];
  const emitted: EmittedAsset[] = [];
  for (const output of outputs) {
    if (!("output" in output)) continue;
    for (const asset of output.output) {
      if (asset.type !== "asset" || !asset.fileName.endsWith(".css")) continue;
      emitted.push({
        name: asset.fileName,
        css: typeof asset.source === "string" ? asset.source : Buffer.from(asset.source).toString(),
      });
    }
  }
  return emitted;
}

export async function buildStylesheets(): Promise<BuiltStylesheet[]> {
  const emitted = await emittedStylesheets({
    root: frontendRoot,
    logLevel: "silent",
    build: { write: false },
  });

  return emitted.map((asset) => ({
    // Where `vite build` would have written it. The build is in memory, but a reader chasing a
    // finding runs the real build, and the name is a function of the content either way.
    file: path.join(frontendRoot, "dist", asset.name),
    name: asset.name,
    css: asset.css,
  }));
}

const PROBE_SPECIFIER = "syncr:barrel-probe";
// A leading NUL is rollup's convention for a module no filesystem holds, and it keeps every other
// plugin's resolver off it.
const PROBE_ID = `\0${PROBE_SPECIFIER}`;

function probeEntry(from: string, component: string): Plugin {
  const code = `import { ${component} } from ${JSON.stringify(from)};\nexport default ${component};\n`;
  return {
    name: "syncr:barrel-probe",
    resolveId: (id) => (id === PROBE_SPECIFIER ? PROBE_ID : null),
    load: (id) => (id === PROBE_ID ? code : null),
  };
}

/** The CSS one named import builds to, with nothing else in the graph. */
export async function buildProbeStylesheet(from: string, component: string): Promise<string> {
  const emitted = await emittedStylesheets({
    root: frontendRoot,
    logLevel: "silent",
    plugins: [probeEntry(from, component)],
    build: { write: false, rollupOptions: { input: PROBE_SPECIFIER } },
  });
  return emitted.map((asset) => asset.css).join("\n");
}

export async function buildBarrelPayloads(
  probes: readonly BarrelProbe[] = BARREL_PROBES,
): Promise<BarrelPayload[]> {
  const payloads: BarrelPayload[] = [];
  for (const probe of probes) {
    const throughBarrel = await buildProbeStylesheet(probe.barrel, probe.component);
    const onItsOwn = await buildProbeStylesheet(probe.module, probe.component);
    payloads.push({
      probe,
      throughBarrelBytes: Buffer.byteLength(throughBarrel),
      onItsOwnBytes: Buffer.byteLength(onItsOwn),
    });
  }
  return payloads;
}
