/* Where the committed scripts find the tree they check.
 *
 * Each script runs from anywhere: `just` recipes cd into `frontend`, the git hook runs
 * from the repository root, and CI does either. Resolving from this module's own URL rather
 * than from `process.cwd()` is what makes all three agree. */

import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

/** `frontend/` */
export const frontendRoot = path.resolve(here, "..", "..");

/** The repository root, which is `frontend/`'s parent. */
export const repoRoot = path.resolve(frontendRoot, "..");

/** The token layer. It stays under `frontend/src/` because the reference sheets link it. */
export const tokenDir = path.join(frontendRoot, "src", "tokens");

/** The token entry point every reference sheet links. */
export const tokenEntry = path.join(tokenDir, "index.css");

/** The rendered reference sheets, including the two probes under `scratch/`. */
export const designSheetDir = path.join(repoRoot, "docs", "design");

/** Application and kit source. Excludes `tokens/`, which is the layer being enforced. */
export const appSourceDir = path.join(frontendRoot, "src");

/** The kit. A state channel may be assigned in exactly one file under here. */
export const kitDir = path.join(appSourceDir, "ui");

/** The committed OpenAPI document, generated from the api by `just contract`. */
export const openapiDocument = path.join(frontendRoot, "openapi.json");

/** The committed types, generated from the document by the same recipe. */
export const generatedSchema = path.join(appSourceDir, "api", "schema.d.ts");

/** The options the application itself is compiled with. */
export const tsconfig = path.join(frontendRoot, "tsconfig.json");

/** A path relative to the repository root, for messages a reader can paste into an editor. */
export function relativeToRepo(absolutePath: string): string {
  return path.relative(repoRoot, absolutePath);
}
