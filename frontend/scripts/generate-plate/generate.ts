/* Turning one public-domain source into one committed plate, and recording where it came from.
 *
 * THE INK IS RESOLVED FROM THE TOKEN LAYER, never chosen here. A plate is baked bytes, so its ink cannot be a
 * `var()` at render time, and a hex in this file would be the one place in the product where a pigment was picked
 * rather than read. `--ink-deep` is what a plate draws in, resolved through the same reader the contrast ledgers
 * use, and the manifest records which token it was so a retuned ramp is a regeneration rather than a mystery.
 *
 * THE SUBJECT IS NOT VALIDATED, AND THAT IS DELIBERATE. Whether an image is an orrery or a bicycle is not a thing
 * a script can tell; what a script CAN do is refuse to write a plate with no source, no licence and no subject
 * recorded, which is what makes the manifest reviewable. */

import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { resolveColourToken } from "../lib/tokens.ts";
import { dither, scaleToWidth } from "./dither.ts";
import { decodeToGray, encodeBitmap } from "./png.ts";
import { readManifest, withRecord, writeManifest, type PlateRecord } from "./manifest.ts";

/** The plate is drawn in the deepest ink in the system, which is what a page title and a panel header take. */
export const INK_TOKEN = "--ink-deep";
const PAPER_TOKEN = "--paper-raised";

export interface GeneratePlateRequest {
  /** The plate's id, which becomes its file name. */
  readonly id: string;
  readonly subject: string;
  /** A URL, or a path to an already-downloaded source. */
  readonly source: string;
  readonly licence: string;
  readonly author: string;
  /** The plate's width in pixels. The height follows the source's own proportion. */
  readonly width: number;
  /** Steepens the source around its midpoint before dithering. 1 leaves it alone. */
  readonly contrast?: number | undefined;
  /** Where the plates and their manifest live. */
  readonly outputDir: string;
}

export interface GeneratePlateResult {
  readonly record: PlateRecord;
  readonly file: string;
  readonly bytes: number;
}

async function readSource(source: string): Promise<Buffer> {
  if (!/^https?:\/\//.test(source)) return readFile(source);
  const response = await fetch(source, {
    headers: { "user-agent": "syncr-plate-generator (development tool)" },
  });
  if (!response.ok) throw new Error(`${source} answered ${response.status}`);
  return Buffer.from(await response.arrayBuffer());
}

function required(request: GeneratePlateRequest): void {
  const missing = (["id", "subject", "source", "licence"] as const).filter(
    (field) => request[field].trim() === "",
  );
  if (missing.length > 0) {
    throw new Error(
      `a plate needs ${missing.join(", ")}: the manifest is what makes the provenance auditable, ` +
        "so a plate with nothing recorded is not written",
    );
  }
}

export async function generatePlate(request: GeneratePlateRequest): Promise<GeneratePlateResult> {
  required(request);

  const source = await readSource(request.source);
  const scaled = scaleToWidth(decodeToGray(source), request.width);
  const bitmap = dither(scaled, request.contrast ?? 1);
  const plate = encodeBitmap(bitmap, {
    ink: await resolveColourToken(INK_TOKEN),
    paper: await resolveColourToken(PAPER_TOKEN),
  });

  const file = path.join(request.outputDir, `${request.id}.png`);
  await mkdir(request.outputDir, { recursive: true });
  await writeFile(file, plate);

  const record: PlateRecord = {
    id: request.id,
    subject: request.subject,
    source: request.source,
    licence: request.licence,
    author: request.author,
    sourceDigest: `sha256:${createHash("sha256").update(source).digest("hex")}`,
    inkToken: INK_TOKEN,
    width: bitmap.width,
    height: bitmap.height,
  };

  const manifestFile = path.join(request.outputDir, "manifest.json");
  await writeManifest(manifestFile, withRecord(await readManifest(manifestFile), record));

  return { record, file, bytes: plate.length };
}
