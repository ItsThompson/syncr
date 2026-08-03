/* THE PLATE MANIFEST: WHERE EVERY PLATE CAME FROM, AND UNDER WHAT LICENCE.
 *
 * Illustration in this product is GENERATED, not licensed per asset, and the manifest is what makes that claim
 * auditable rather than asserted: one entry per committed plate, naming the source, its licence, the subject, and
 * the digest of the bytes the plate was made from. A plate whose provenance is not recorded is a plate nobody can
 * clear, and a plate is easier to add than to trace afterwards.
 *
 * THE DIGEST IS OF THE SOURCE, NOT THE PLATE. Two people asking the generator for the same plate from the same
 * source get the same digest, so an entry can be verified against the original download rather than trusted. The
 * source itself is not committed: it is a megabyte of someone else's file, and the URL plus the digest is what a
 * regeneration needs.
 *
 * The file is written sorted by id and with a trailing newline, so a second plate is a one-entry diff rather than a
 * reordering of the whole file. */

import { readFile, writeFile } from "node:fs/promises";

export interface PlateRecord {
  /** The plate's id, which is also its file name. */
  readonly id: string;
  /** What it depicts: horological and astronomical instruments, and nothing else. */
  readonly subject: string;
  /** Where the source came from, as a URL a reader can open. */
  readonly source: string;
  /** The licence the source carries, in the words its host uses. */
  readonly licence: string;
  /** Who made the source, where the host names them. */
  readonly author: string;
  /** sha256 of the source bytes, so a regeneration can be verified against the original. */
  readonly sourceDigest: string;
  /** The token the plate's ink was baked from, so the pigment is the product's rather than a chosen hex. */
  readonly inkToken: string;
  readonly width: number;
  readonly height: number;
}

export interface PlateManifest {
  readonly plates: readonly PlateRecord[];
}

export async function readManifest(file: string): Promise<PlateManifest> {
  try {
    const parsed: unknown = JSON.parse(await readFile(file, "utf8"));
    if (typeof parsed !== "object" || parsed === null || !("plates" in parsed)) {
      throw new Error("the manifest has no plates array");
    }
    return parsed as PlateManifest;
  } catch (cause) {
    if (cause instanceof Error && "code" in cause && cause.code === "ENOENT") return { plates: [] };
    throw cause;
  }
}

/** The manifest with one record added or replaced, sorted by id. */
export function withRecord(manifest: PlateManifest, record: PlateRecord): PlateManifest {
  const others = manifest.plates.filter((plate) => plate.id !== record.id);
  return { plates: [...others, record].toSorted((one, two) => one.id.localeCompare(two.id)) };
}

export async function writeManifest(file: string, manifest: PlateManifest): Promise<void> {
  await writeFile(file, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
}
