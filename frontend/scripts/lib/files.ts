/* Walking a directory for the files a check reads. */

import { readdir } from "node:fs/promises";
import path from "node:path";

const IGNORED_DIRECTORIES = new Set(["node_modules", "dist", "coverage", "__fixtures__"]);

export async function filesUnder(
  root: string,
  extensions: readonly string[],
): Promise<string[]> {
  const entries = await readdir(root, { withFileTypes: true, recursive: true });
  return entries
    .filter((entry) => entry.isFile())
    .filter((entry) => extensions.some((extension) => entry.name.endsWith(extension)))
    .filter((entry) => !path.relative(root, entry.parentPath).split(path.sep).some(isIgnored))
    .map((entry) => path.join(entry.parentPath, entry.name))
    .toSorted();
}

function isIgnored(segment: string): boolean {
  return IGNORED_DIRECTORIES.has(segment);
}
