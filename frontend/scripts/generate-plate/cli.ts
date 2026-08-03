#!/usr/bin/env node
/* Generate one illustration plate. A developer tool, not a gate: it is run when a plate is added.
 *
 *   node scripts/generate-plate/cli.ts \
 *     --id astrolabe --subject "Planispheric astrolabe" \
 *     --source https://upload.wikimedia.org/... --licence "Public domain" --author "Frb ds" \
 *     --width 480 --contrast 1.35
 *
 * SUBJECTS ARE HOROLOGICAL AND ASTRONOMICAL INSTRUMENTS: orreries, sundials, escapement mechanisms, astrolabes,
 * star charts. Thematically exact for a scheduler, and the constraint is what keeps five plates from becoming a
 * mood board.
 *
 * The plate lands in `src/assets/plates/` beside the manifest that records its source and licence. Both are
 * committed; the source download is not. */

import path from "node:path";

import { frontendRoot, relativeToRepo } from "../lib/paths.ts";
import { generatePlate } from "./generate.ts";

function option(name: string, fallback?: string): string {
  const at = process.argv.indexOf(`--${name}`);
  const value = at === -1 ? undefined : process.argv[at + 1];
  if (value === undefined || value.startsWith("--")) {
    if (fallback !== undefined) return fallback;
    throw new Error(`--${name} is required`);
  }
  return value;
}

const outputDir = path.join(frontendRoot, "src", "assets", "plates");

const result = await generatePlate({
  id: option("id"),
  subject: option("subject"),
  source: option("source"),
  licence: option("licence"),
  author: option("author", "unattributed"),
  width: Number.parseInt(option("width", "480"), 10),
  contrast: Number.parseFloat(option("contrast", "1")),
  outputDir,
});

process.stdout.write(
  `plate ${result.record.id}: ${result.record.width}x${result.record.height}, ` +
    `${(result.bytes / 1000).toFixed(2)} kB\n` +
    `  ${relativeToRepo(result.file)}\n` +
    `  source ${result.record.source}\n` +
    `  licence ${result.record.licence}, ink ${result.record.inkToken}\n`,
);
