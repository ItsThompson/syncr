/* Building the application in memory, so the gate reads the artifact rather than a stale `dist/`.
 *
 * `write: false` is deliberate: a check must not leave build output behind, and reading a `dist/`
 * somebody else produced would make the gate's verdict depend on when that build ran. Vite resolves
 * `vite.config.ts` itself, so this compiles through the same plugin chain a deploy does. */

import path from "node:path";
import { build } from "vite";

import { frontendRoot } from "../lib/paths.ts";
import type { BuiltStylesheet } from "./check.ts";

export async function buildStylesheets(): Promise<BuiltStylesheet[]> {
  const result = await build({
    root: frontendRoot,
    logLevel: "silent",
    build: { write: false },
  });

  const outputs = Array.isArray(result) ? result : [result];
  const stylesheets: BuiltStylesheet[] = [];
  for (const output of outputs) {
    if (!("output" in output)) continue;
    for (const asset of output.output) {
      if (asset.type !== "asset" || !asset.fileName.endsWith(".css")) continue;
      stylesheets.push({
        // Where `vite build` would have written it. The build is in memory, but a reader chasing a
        // finding runs the real build, and the name is a function of the content either way.
        file: path.join(frontendRoot, "dist", asset.fileName),
        name: asset.fileName,
        css: typeof asset.source === "string" ? asset.source : Buffer.from(asset.source).toString(),
      });
    }
  }
  return stylesheets;
}
